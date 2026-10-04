"""Memory candidate extractor.

Pure function from (user turn, twin turn, stable profile) → an
`ExtractionResult`. Uses the `LLMProvider` interface — no vendor SDK
imports.

Design choices:

- **Trivial-input filter.** User turns under 4 non-whitespace tokens are
  not sent to the LLM at all; return `ExtractionResult([])`.
- **Never raises.** JSON parse errors, provider errors, oversized output —
  all become `ExtractionResult([], error=<reason>)` with no logging done
  here. The caller (background task) adds structured IDs to the log.
- **Strict schema.** The LLM is asked to return a JSON object matching
  `_ExtractionEnvelope`. Anything else is treated as an empty extraction.
- **No profile mutation.** The extractor reads `TwinProfile` for context
  (communication style, basic profile) but never writes back. Reinforced
  by `test_profile_unchanged_after_extraction`.
- **No message content in logs.** The extractor does not log the user
  message or the twin reply. The task function logs IDs only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.llm.interface import LLMMessage, LLMProvider, LLMRequest
from app.memory.schemas import MemoryCandidateDraft
from app.twin.models import TwinProfile


class _ExtractionEnvelope(BaseModel):
    """Shape the LLM must return."""

    candidates: list[MemoryCandidateDraft] = Field(default_factory=list)


@dataclass
class ExtractionResult:
    """What the extractor returns.

    `error` is `None` on the normal path (empty or non-empty drafts). On
    failure it is a short, non-sensitive reason suitable for structured
    logging: `provider_error:<ExceptionClass>` or `parse_error`.
    """

    drafts: list[MemoryCandidateDraft] = field(default_factory=list)
    error: str | None = None


SYSTEM_PROMPT = """You are the memory extractor for a Personal AI Twin.

Given one user→twin turn pair, decide what — if anything — is worth saving
as a durable memory for the user. Be CONSERVATIVE. Save only things that
would still be true or useful next week.

Return STRICT JSON matching this schema:

{
  "candidates": [
    {
      "type": "FACT" | "PREFERENCE" | "EXPERIENCE" | "GOAL",
      "content": "<one short sentence>",
      "confidence": 0.0-1.0,
      "importance": 0.0-1.0,
      "rationale": "<why this is worth remembering>"
    }
  ]
}

Rules:
- Return {"candidates": []} if nothing durable was said.
- Do NOT save pleasantries, greetings, acknowledgements, fleeting moods,
  or questions.
- Do NOT infer or speculate — only save what the user explicitly stated.
- Do NOT include health inferences the user did not state.
- No prose outside the JSON object.
"""


class MemoryExtractor:
    def __init__(self, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def extract(
        self,
        *,
        user_message: str,
        twin_response: str,
        twin_profile: TwinProfile | None,
    ) -> ExtractionResult:
        if _is_trivial(user_message):
            return ExtractionResult(drafts=[], error=None)

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(
                    role="user",
                    content=_build_user_prompt(user_message, twin_response, twin_profile),
                ),
            ],
            model=self._model,
            temperature=0.0,
            max_tokens=1024,
            metadata={"purpose": "memory_extraction"},
        )

        try:
            response = await self._provider.generate_response(request)
        except Exception as exc:
            return ExtractionResult(
                drafts=[],
                error=f"provider_error:{type(exc).__name__}",
            )

        drafts = _parse_candidates(response.content)
        return ExtractionResult(drafts=drafts, error=None)


# -------- helpers --------


def _is_trivial(text: str) -> bool:
    """Fewer than 4 non-whitespace tokens → not worth extracting."""
    return len(text.strip().split()) < 4


def _build_user_prompt(user_message: str, twin_response: str, profile: TwinProfile | None) -> str:
    profile_line = ""
    if profile is not None:
        bp = ", ".join(f"{k}={v!r}" for k, v in (profile.basic_profile or {}).items())
        profile_line = (
            f"Twin stable profile: style={profile.communication_style_preset}, "
            f"{bp or 'no basic_profile fields'}.\n"
        )
    return (
        f"{profile_line}"
        f"User said: {user_message!r}\n"
        f"Twin replied: {twin_response!r}\n"
        f"Return the JSON object now."
    )


def _parse_candidates(content: str) -> list[MemoryCandidateDraft]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        first_newline = text.find("\n")
        if first_newline != -1 and len(text[:first_newline].strip()) < 10:
            text = text[first_newline + 1 :]
        text = text.strip("`").strip()

    raw_candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw_candidates.append(text[start : end + 1])

    for raw in raw_candidates:
        try:
            data: Any = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        try:
            envelope = _ExtractionEnvelope.model_validate(data)
        except ValidationError:
            continue
        return list(envelope.candidates)

    return []
