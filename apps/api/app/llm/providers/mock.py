"""MockProvider — deterministic echo used for tests and offline dev.

Given a message list, returns a reply that:
- names itself as the twin
- quotes back the last user message (or, if none, acknowledges the system prompt)
This is enough for the pipeline tests to assert end-to-end behaviour without
any external network.
"""

from __future__ import annotations

from typing import ClassVar

from app.llm.interface import LLMProvider, LLMRequest, LLMResponse


class MockProvider(LLMProvider):
    provider_name: ClassVar[str] = "mock"

    async def generate_response(self, request: LLMRequest) -> LLMResponse:
        last_user = next(
            (m for m in reversed(request.messages) if m.role == "user"), None
        )
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
