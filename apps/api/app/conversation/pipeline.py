"""Sprint 1 twin response pipeline.

Deliberately simple:
    Authenticated user
      → Twin
      → Conversation history
      → Twin Profile
      → Context builder
      → LLM Provider
      → Twin message
      → Persist

No memory retrieval. No reflection. No emotional inference. Those live in
`docs/architecture/twin-engine.md` and land in Sprint 2+.
"""

from __future__ import annotations

from app.config import get_settings
from app.conversation.models import Conversation, Message
from app.llm.interface import LLMMessage, LLMProvider, LLMRequest, LLMResponse
from app.twin.models import Twin


def build_system_prompt(twin: Twin) -> str:
    """Small, deterministic system prompt from the Twin profile."""
    profile = twin.profile
    lines = [
        f"You are the Personal AI Twin of the user (twin display name: {twin.display_name}).",
        "You are the evolving personal intelligence — the avatar is the interface, "
        "the intelligence is the product. Keep responses grounded and honest.",
        f"Communication style preset: {profile.communication_style_preset}.",
    ]
    if profile.communication_style_notes:
        lines.append(f"Additional style notes from the user: {profile.communication_style_notes}")
    if profile.basic_profile:
        lines.append(
            "Basic profile the user shared: "
            + ", ".join(f"{k}={v!r}" for k, v in profile.basic_profile.items())
        )
    return "\n".join(lines)


def build_llm_request(
    twin: Twin,
    history: list[Message],
    user_message_content: str,
) -> LLMRequest:
    """Assemble the LLM request from profile + history + new message.

    History is included verbatim (Sprint 1). A token-budgeted context builder
    with retrieval lands in Sprint 2 (see docs/architecture/twin-engine.md).
    """
    settings = get_settings()
    messages: list[LLMMessage] = [
        LLMMessage(role="system", content=build_system_prompt(twin))
    ]
    for m in history:
        # System messages in history are already reflected in the system prompt;
        # forward only user/twin turns to the provider.
        if m.role == "user":
            messages.append(LLMMessage(role="user", content=m.content))
        elif m.role == "twin":
            messages.append(LLMMessage(role="assistant", content=m.content))
    messages.append(LLMMessage(role="user", content=user_message_content))

    return LLMRequest(messages=messages, model=settings.llm_model)


async def run_pipeline(
    twin: Twin,
    conversation: Conversation,
    history: list[Message],
    user_message_content: str,
    provider: LLMProvider,
) -> LLMResponse:
    """Sole entrypoint used by the conversation service.

    Returns the LLM response; the service is responsible for persistence.
    """
    request = build_llm_request(twin, history, user_message_content)
    return await provider.generate_response(request)
