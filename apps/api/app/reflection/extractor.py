"""ReflectionExtractor (Sprint 7).

A pure async function from (confirmed memories + active goals +
recent conversation turns + stable profile) → `ReflectionExtractionResult`.
Uses the `LLMProvider` protocol — never imports a vendor SDK.

Design rules enforced here (mirrors `app.memory.extractor`):

- **Never raises.** JSON parse errors, provider errors, oversized
  output, non-JSON output, kind mismatches, payload shape mismatches —
  all become `ReflectionExtractionResult([], error=<reason>)`. A
  reflection run that failed internally returns an empty list; the
  chat path never sees any of this.
- **No side effects.** The extractor reads a bounded view of the user's
  own data and returns a value. It does NOT write to the DB, it does
  NOT mutate `TwinProfile`, it does NOT call out to anything other
  than the injected `LLMProvider`.
- **Owner-scoped input.** The caller is responsible for passing only
  rows that belong to the authenticated user's twin. The extractor
  does not re-check ownership (the service layer did it when it loaded
  the rows).
- **Strict schema.** The LLM is instructed to return a JSON object
  matching `_ExtractionEnvelope`. Each draft is run through the
  `ReflectionDraft` Pydantic model and the per-kind payload is run
  through its discriminated-union schema. Anything that does not match
  is dropped.
- **No message content in logs.** The extractor logs nothing. The
  service layer logs with IDs only.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from app.llm.interface import LLMMessage, LLMProvider, LLMRequest
from app.reflection.models import REFLECTION_KINDS
from app.reflection.schemas import (
    GoalUpdatePayload,
    InsightPayload,
    MemoryDedupPayload,
    ProfileUpdatePayload,
    ReflectionDraft,
)


class _ExtractionEnvelope(BaseModel):
    """The strict LLM response shape."""

    candidates: list[ReflectionDraft] = Field(default_factory=list)


@dataclass
class ReflectionExtractionResult:
    """What `ReflectionExtractor.extract` returns.

    `error` is `None` on the normal path (empty or non-empty drafts).
    On failure it is a short, non-sensitive reason suitable for
    structured logging: `provider_error:<ExceptionClass>` or
    `parse_error` or `empty_response`.
    """

    drafts: list[ReflectionDraft] = field(default_factory=list)
    error: str | None = None


SYSTEM_PROMPT = """You are the reflection extractor for a Personal AI Twin.

You read a BOUNDED set of the user's own CONFIRMED memories, their ACTIVE
goals, and a small window of their recent conversation turns, and you
PROPOSE user-confirmable observations. The user is the sole author of
durable changes — you only propose.

Return STRICT JSON matching this schema:

{
  "candidates": [
    {
      "kind": "profile_update" | "memory_dedup" | "goal_update" | "insight",
      "payload": { ... see per-kind rules below ... },
      "rationale": "<short, non-sensitive reason the user can read>",
      "source_memory_ids": ["<uuid>", ...],
      "source_goal_ids": ["<uuid>", ...],
      "confidence": 0.0-1.0,
      "importance": 0.0-1.0
    }
  ]
}

Per-kind payload rules:

- "profile_update": { "kind": "profile_update",
                      "field": "communication_style_notes" | "basic_profile",
                      "current_value": <scalar | object | null>,
                      "proposed_value": <scalar | object>,
                      "rationale": "<short reason>" }
  Only propose this when at least TWO source_memory_ids independently
  support it, and only for the two listed fields.

- "memory_dedup": { "kind": "memory_dedup",
                    "superseded_memory_id": "<uuid>",
                    "canonical_memory_id": "<uuid>",
                    "rationale": "<short reason>" }
  Only when the two memories say the same thing. Pick the canonical
  memory as the one that was most recently confirmed. Both IDs MUST
  appear in source_memory_ids.

- "goal_update": { "kind": "goal_update",
                   "goal_id": "<uuid>",
                   "note": "<short observation about progress>",
                   "rationale": "<short reason>" }
  Non-destructive: the service only writes a GoalEvent, never changes
  title / status / priority. The goal_id MUST appear in
  source_goal_ids.

- "insight": { "kind": "insight",
               "headline": "<<=200 chars>",
               "body": "<<=4000 chars>",
               "rationale": "<short reason>" }
  Informational. Confirming an insight does not create a Memory and
  does not mutate TwinProfile.

Rules:
- Return {"candidates": []} if nothing is worth proposing.
- Be CONSERVATIVE. Over-proposing erodes user trust.
- Do NOT propose health inferences the user did not state.
- Do NOT propose anything that would persist a protected attribute.
- Do NOT reference ids or scores from this prompt in `rationale` or
  payload fields — those are for the audit layer, not the user.
- No prose outside the JSON object.
"""


class ReflectionExtractor:
    def __init__(self, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def extract(
        self,
        *,
        memories: list[tuple[uuid.UUID, str, str]],
        goals: list[tuple[uuid.UUID, str, str | None, int, str]],
        recent_turns: list[tuple[str, str]],
        profile_style: str,
        profile_notes: str | None,
        basic_profile: dict[str, object] | None,
    ) -> ReflectionExtractionResult:
        """Propose reflection candidates.

        `memories` is a list of (id, type, content).
        `goals` is a list of (id, title, description, priority, status).
        `recent_turns` is a list of (role, content).

        The caller is responsible for passing bounded, owner-scoped
        rows. The extractor neither queries nor caches anything.
        """
        if not memories and not goals and not recent_turns:
            # Nothing to reflect on. Return cleanly without calling the LLM.
            return ReflectionExtractionResult(drafts=[], error=None)

        user_prompt = _build_user_prompt(
            memories=memories,
            goals=goals,
            recent_turns=recent_turns,
            profile_style=profile_style,
            profile_notes=profile_notes,
            basic_profile=basic_profile,
        )
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_prompt),
            ],
            model=self._model,
            temperature=0.0,
            max_tokens=2048,
            metadata={"purpose": "reflection_extraction"},
        )

        try:
            response = await self._provider.generate_response(request)
        except Exception as exc:
            return ReflectionExtractionResult(
                drafts=[],
                error=f"provider_error:{type(exc).__name__}",
            )

        if not response.content.strip():
            return ReflectionExtractionResult(drafts=[], error="empty_response")

        drafts, parse_error = _parse_candidates(response.content)
        return ReflectionExtractionResult(drafts=drafts, error=parse_error)


# -------- helpers --------

_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "profile_update": ProfileUpdatePayload,
    "memory_dedup": MemoryDedupPayload,
    "goal_update": GoalUpdatePayload,
    "insight": InsightPayload,
}


def _parse_candidates(raw: str) -> tuple[list[ReflectionDraft], str | None]:
    """Parse the LLM's JSON output into validated drafts.

    Drafts that fail validation (wrong kind, wrong payload shape,
    unknown fields) are DROPPED, not substituted. The function
    returns `(drafts, error)` where `error` is `None` unless the
    envelope itself was unparseable; a non-empty `drafts` with
    `error is None` is the happy path.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [], "parse_error"

    try:
        envelope = _ExtractionEnvelope.model_validate(parsed)
    except ValidationError:
        return [], "parse_error"

    out: list[ReflectionDraft] = []
    for draft in envelope.candidates:
        if draft.kind not in REFLECTION_KINDS:
            continue
        payload_model = _PAYLOAD_MODELS[draft.kind]
        try:
            payload_model.model_validate(draft.payload)
        except ValidationError:
            continue
        out.append(draft)
    return out, None


def _build_user_prompt(
    *,
    memories: list[tuple[uuid.UUID, str, str]],
    goals: list[tuple[uuid.UUID, str, str | None, int, str]],
    recent_turns: list[tuple[str, str]],
    profile_style: str,
    profile_notes: str | None,
    basic_profile: dict[str, object] | None,
) -> str:
    lines: list[str] = []
    lines.append(f"Twin style preset: {profile_style}.")
    if profile_notes:
        lines.append(f"Current style notes: {profile_notes}")
    if basic_profile:
        parts = ", ".join(f"{k}={v!r}" for k, v in sorted(basic_profile.items()))
        lines.append(f"Current basic_profile: {parts}")

    if memories:
        lines.append("")
        lines.append("Confirmed memories (id, type, content):")
        for mid, mtype, mcontent in memories:
            # Content is bounded by the caller via ContextBudget-like
            # slicing. We quote-escape so stray braces inside the
            # content don't look like JSON to the LLM.
            lines.append(f"- id={mid} type={mtype} :: {mcontent!r}")

    if goals:
        lines.append("")
        lines.append("Active goals (id, title, description, priority, status):")
        for gid, title, desc, pri, status in goals:
            desc_part = f" desc={desc!r}" if desc else ""
            lines.append(f"- id={gid} priority={pri} status={status} title={title!r}{desc_part}")

    if recent_turns:
        lines.append("")
        lines.append("Recent conversation turns (role, content):")
        for role, content in recent_turns:
            lines.append(f"- {role}: {content!r}")

    lines.append("")
    lines.append("Return the JSON object now.")
    return "\n".join(lines)
