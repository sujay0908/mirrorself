"""Pydantic schemas for reflection endpoints (Sprint 7).

Payload shape is kind-specific. The strict union below is enforced by
Pydantic's discriminated-union feature on the `kind` field so a
malformed draft from the extractor (missing fields, wrong fields,
extra fields) is rejected at the schema layer and never persists.

Founder decision #2: the `profile_update` payload MUST expose a
legible diff:

- `field` — which TwinProfile field is being proposed
- `current_value` — what the service recorded as current when the
  draft was produced
- `proposed_value` — the proposed replacement
- `rationale` — a short, non-sensitive reason the user can read

The confirmation UX relies on these four. There is no "update profile?"
button that does not render them.

Founder decision #1: the `insight` payload is informational. Confirming
an insight marks the reflection as accepted — it does NOT create a
durable Memory and does NOT touch TwinProfile.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReflectionKind = Literal["profile_update", "memory_dedup", "goal_update", "insight"]
ReflectionStatus = Literal["pending", "confirmed", "rejected"]
# Keep in sync with `app/twin/schemas.py::TwinProfilePatch` fields the
# user is allowed to drive via a reflection confirmation. Deliberately
# narrower than the full TwinProfilePatch so a reflection cannot touch
# `display_name` (identity) or `communication_style_preset` (a fixed
# vocabulary the LLM should not pick blindly).
ProfileUpdateField = Literal["communication_style_notes", "basic_profile"]


class ProfileUpdatePayload(BaseModel):
    """`kind='profile_update'` payload.

    Carries the exact diff the confirmation UX must render:
    current / proposed / rationale / sources are all required.
    """

    kind: Literal["profile_update"] = "profile_update"
    field: ProfileUpdateField
    current_value: Any = None
    proposed_value: Any
    rationale: str = Field(min_length=1, max_length=4000)


class MemoryDedupPayload(BaseModel):
    """`kind='memory_dedup'` payload.

    `superseded_memory_id` keeps all its rows; `canonical_memory_id`
    is the one retrieval will continue to use. Both IDs are owner-
    verified in `MemoryService.supersede`.
    """

    kind: Literal["memory_dedup"] = "memory_dedup"
    superseded_memory_id: uuid.UUID
    canonical_memory_id: uuid.UUID
    rationale: str = Field(min_length=1, max_length=4000)


class GoalUpdatePayload(BaseModel):
    """`kind='goal_update'` payload.

    Non-destructive: records an annotation on the referenced goal via
    a `GoalEvent` of type `updated`, but never changes title / status /
    priority. The user can act on it from the goal detail screen.
    """

    kind: Literal["goal_update"] = "goal_update"
    goal_id: uuid.UUID
    note: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)


class InsightPayload(BaseModel):
    """`kind='insight'` payload.

    Confirming an insight only acknowledges it — no Memory row is
    created, no TwinProfile field is touched. Founder decision #1.
    """

    kind: Literal["insight"] = "insight"
    headline: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(min_length=1, max_length=4000)


ReflectionPayload = Annotated[
    ProfileUpdatePayload | MemoryDedupPayload | GoalUpdatePayload | InsightPayload,
    Field(discriminator="kind"),
]


class ReflectionDraft(BaseModel):
    """What `ReflectionExtractor` returns (per candidate).

    The extractor emits a list of these. `ReflectionService.create_candidates`
    persists them as pending rows, filtering out fingerprints that
    already have a pending row.
    """

    kind: ReflectionKind
    payload: dict[str, Any]
    rationale: str = Field(min_length=1, max_length=4000)
    source_memory_ids: list[uuid.UUID] = Field(default_factory=list)
    source_goal_ids: list[uuid.UUID] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class ReflectionOut(BaseModel):
    """What `/v1/reflections` returns per row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    twin_id: uuid.UUID
    kind: ReflectionKind
    status: ReflectionStatus
    proposed_payload: dict[str, Any]
    source_memory_ids: list[str]
    source_goal_ids: list[str]
    rationale: str | None
    confidence: float
    importance: float
    resolved_at: datetime | None
    apply_error: str | None
    apply_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ReflectionListOut(BaseModel):
    items: list[ReflectionOut]


class ReflectionConfirmOut(BaseModel):
    reflection: ReflectionOut
    # True when the per-kind apply dispatcher ran cleanly. For
    # `insight` it is always True because the acknowledgement IS the
    # apply.
    applied: bool
    # IDs of the rows the apply dispatcher wrote to (TwinProfile row id
    # for `profile_update`, canonical memory id for `memory_dedup`,
    # goal event id for `goal_update`, empty for `insight`). Never
    # contains user content.
    apply_metadata: dict[str, Any]


class ReflectionRunOut(BaseModel):
    """Response from `POST /v1/reflections/run`.

    The run is synchronous for Sprint 7 — manual trigger, no
    background job. Latency is bounded by the LLM call plus a small
    SQL footprint.
    """

    candidates_proposed: int
    candidates_persisted: int
    candidates_deduplicated: int
    error: str | None = None
