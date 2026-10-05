"""Twin response pipeline — Sprint 3 / extended in Sprint 6.

Sprint 2 assembled the system prompt from the Twin profile only. Sprint 3
expects a fully built `TwinContext` (profile + retrieved memories + recent
turns + provenance). Sprint 6 lets the caller optionally pass a
`TwinState` (session-local intent + context policy) so the renderer can
emit a one-line "what this turn is about" hint.

Keeping the context assembly OUTSIDE this function means:

- the pipeline is unit-testable with a hand-built TwinContext.
- memory retrieval failure is handled by the caller (ConversationService),
  which can degrade to an empty-memory TwinContext — the pipeline neither
  retries nor cares.
- the `TwinContext` + `TwinState` pair doubles as the trace record for
  "what did the LLM see".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import get_settings
from app.llm.interface import LLMMessage, LLMProvider, LLMRequest, LLMResponse
from app.memory.context import TwinContext

if TYPE_CHECKING:
    from app.conversation.state import TwinState


def build_llm_request(
    context: TwinContext,
    user_message_content: str,
    twin_state: TwinState | None = None,
) -> LLMRequest:
    settings = get_settings()
    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=context.to_system_prompt(twin_state))
    ]
    for turn in context.recent_turns:
        role = "assistant" if turn.role == "twin" else "user"
        messages.append(LLMMessage(role=role, content=turn.content))
    messages.append(LLMMessage(role="user", content=user_message_content))
    return LLMRequest(messages=messages, model=settings.llm_model)


async def run_pipeline(
    *,
    context: TwinContext,
    user_message_content: str,
    provider: LLMProvider,
    twin_state: TwinState | None = None,
) -> LLMResponse:
    request = build_llm_request(context, user_message_content, twin_state=twin_state)
    return await provider.generate_response(request)
