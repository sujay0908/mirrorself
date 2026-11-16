"""MockProvider — deterministic echo used for tests and offline dev.

Given a message list, returns a reply that:
- names itself as the twin
- quotes back the last user message (or, if none, acknowledges the system prompt)
This is enough for the pipeline tests to assert end-to-end behaviour without
any external network.

It can also stand in for a real model's *timing and failures*, which is what
load tests and failure drills need:

- `latency_ms` (from `MOCK_LLM_LATENCY_MS`) delays every reply, so a load
  test holds connections for as long as a real model call would.
- a user message containing `[[mock:sleep=N]]` delays that one reply by N
  milliseconds; `[[mock:fail]]` makes that one call raise.

Production refuses to start with this provider selected, so none of this is
reachable there.
"""

from __future__ import annotations

import asyncio
import re
from typing import ClassVar

from app.llm.interface import LLMProvider, LLMRequest, LLMResponse

_SLEEP_DIRECTIVE = re.compile(r"\[\[mock:sleep=(\d{1,5})\]\]")
_FAIL_DIRECTIVE = "[[mock:fail]]"
_MAX_DIRECTIVE_SLEEP_MS = 30_000


class MockProvider(LLMProvider):
    provider_name: ClassVar[str] = "mock"

    def __init__(self, latency_ms: int = 0) -> None:
        self._latency_ms = max(0, latency_ms)

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        last_user = next((m for m in reversed(request.messages) if m.role == "user"), None)
        delay_ms = self._latency_ms
        if last_user is not None:
            directive = _SLEEP_DIRECTIVE.search(last_user.content)
            if directive is not None:
                delay_ms = min(int(directive.group(1)), _MAX_DIRECTIVE_SLEEP_MS)
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        if last_user is not None and _FAIL_DIRECTIVE in last_user.content:
            raise RuntimeError("mock provider failure requested")

        if last_user is None:
            reply = "twin(mock): hello — I have no user message to respond to yet."
        else:
            reply = f"twin(mock): I heard you say: {last_user.content}"

        input_tokens = sum(len(m.content.split()) for m in request.messages)
        output_tokens = len(reply.split())
        return LLMResponse(
            content=reply,
            provider=self.provider_name,
            model=request.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason="stop",
            metadata={"echo": True},
        )
