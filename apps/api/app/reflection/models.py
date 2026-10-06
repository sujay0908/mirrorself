"""ORM for reflection_candidates (Sprint 7).

A `ReflectionCandidate` is a proposal the Twin's reflection extractor
emitted after reading the user's confirmed memories, active goals and
recent conversation turns. Every row is `status='pending'` until the
user confirms or rejects it. Only confirmed rows ever trigger a
mutation elsewhere (profile, memory, goal); even then, the mutation
runs through the existing service boundary — the DB write is NEVER
made directly by this module or by the reflection extractor.

Rules enforced here (and reinforced by tests):

- `kind` is one of four values. The CHECK constraint pins the set so
  a future contributor cannot smuggle a fifth kind in without a
  migration.
- `status` is `pending` / `confirmed` / `rejected`. There is no
  `expired` state in Sprint 7 — a scheduled TTL task is out of scope.
- `source_memory_ids` and `source_goal_ids` are JSON arrays of UUID
  strings. Each confirmed candidate's audit answer to
  "why does my Twin suggest this?" is composed from these rows plus
  `rationale`.
- `fingerprint` is a deterministic hash over
  (twin_id, kind, sorted(source_memory_ids), sorted(source_goal_ids))
  used by `ReflectionService.create_candidates` to drop obvious
  re-proposals from a repeat `/v1/reflections/run`. See
  `app.reflection.service._candidate_fingerprint`.
- Ownership scoping is via `twin_id` + `user_id`; both FKs cascade
  with the owning twin.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin

REFLECTION_KINDS: tuple[str, ...] = (
    "profile_update",
    "memory_dedup",
    "goal_update",
    "insight",
)
REFLECTION_STATUSES: tuple[str, ...] = ("pending", "confirmed", "rejected")


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class ReflectionCandidate(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "reflection_candidates"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('profile_update','memory_dedup','goal_update','insight')",
            name="reflection_candidates_kind_check",
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','rejected')",
            name="reflection_candidates_status_check",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="reflection_candidates_confidence_check",
        ),
        CheckConstraint(
            "importance >= 0 AND importance <= 1",
            name="reflection_candidates_importance_check",
        ),
        Index(
            "ix_reflection_candidates_twin_status_created",
            "twin_id",
            "status",
            "created_at",
        ),
        # Fingerprint is nullable so legacy inserts (none today) don't
        # trip a NOT NULL on an existing table. The composite index
        # lets `create_candidates` short-circuit duplicate proposals in
        # a single twin's pending backlog.
        Index(
            "ix_reflection_candidates_twin_fingerprint",
            "twin_id",
            "status",
            "fingerprint",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    twin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("twins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Shape depends on kind. Validated at the schema layer, not here.
    proposed_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Provenance arrays. Each entry is a stringified UUID.
    source_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_goal_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    # Deterministic de-duplication fingerprint. See service layer.
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # When the user resolved the candidate (confirm or reject). NULL
    # while pending.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When an apply fails after a `confirm`, we keep the candidate at
    # `status='confirmed'` and record the error here so a future
    # retry endpoint has somewhere to look. Never contains raw user
    # content.
    apply_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Opaque diagnostic bag written by the service when a confirm
    # applied cleanly. IDs and counts only. See
    # `ReflectionService._apply` per-kind write.
    apply_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )
