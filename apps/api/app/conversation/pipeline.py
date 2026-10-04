"""Twin response pipeline — Sprint 3 edition.

Sprint 2 assembled the system prompt from the Twin profile only. Sprint 3
expects a fully built `TwinContext` (profile + retrieved memories + recent
turns + provenance). The pipeline turns that into the LLM message
sequence and calls the provider.

Keeping the context assembly OUTSIDE this function means:

- the pipeline is unit-testable with a hand-built TwinContext.
- memory retrieval failure is handled by the caller (ConversationService),
  which can degrade to an empty-memory TwinContext — the pipeline neither
  retries nor cares.
- the `TwinContext` doubles as the trace record for "what did the LLM see".
"""

from __future__ import annotations

from app.config import get_settings
from app.llm.interface import LLMMessage, LLMProvider, LLMRequest, LLMResponse
from app.memory.context import TwinContext


def build_llm_request(context: TwinContext, user_message_content: str) -> LLMRequest:
    settings = get_settings()
    messages: list[LLMMessage] = [LLMMessage(role="system", content=context.to_system_prompt())]
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
) -> LLMResponse:
    request = build_llm_request(context, user_message_content)
    return await provider.generate_response(request)
