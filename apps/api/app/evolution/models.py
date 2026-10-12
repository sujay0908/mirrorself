"""ORM for `twin_evolution_events` (Sprint 8).

Lifecycle:

- A row is written ONLY after a durable, user-authorized change
  succeeds. Writers:
    * `MemoryService.confirm_candidate` →
        event_type='memory_learned', memory_id=<new memory>
    * `ReflectionService._apply` branches, after a successful commit:
        - memory_dedup  → event_type='memory_consolidated'
        - goal_update   → event_type='goal_updated'
        - profile_update→ event_type='profile_confirmed'
        - insight       → event_type='insight_acknowledged'
          (Sprint 7 founder decision #1 — this is acknowledgement, not
          identity mutation; the mobile UI phrases insight events as
          "You acknowledged…" rather than "Your Twin learned…".)
- Rejected reflections DO NOT create evolution events (Decision 3).

Privacy:

- `summary` is a short, derived string composed from IDs and safe
  metadata. It MUST NOT contain the user's raw message, memory, goal,
  or profile text. The field is capped at 255 characters as a hard
  structural ceiling against future callers.

Ownership:

- `(user_id, twin_id)` and the twin FK cascade with the owning twin.
- RLS: see infra/supabase/policies.sql.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPKMixin

EVOLUTION_EVENT_TYPES: tuple[str, ...] = (
    "memory_learned",
    "memory_consolidated",
    "goal_updated",
    "profile_confirmed",
    "insight_acknowledged",
)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class TwinEvolutionEvent(Base, UUIDPKMixin):
    __tablename__ = "twin_evolution_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'memory_learned','memory_consolidated','goal_updated',"
            "'profile_confirmed','insight_acknowledged'"
            ")",
            name="twin_evolution_events_type_check",
        ),
        Index(
            "ix_twin_evolution_events_twin_created",
            "twin_id",
            "created_at",
        ),
        # Sprint 10: forward-only surface read is `WHERE twin_id = ?
        # AND seq > cursor ORDER BY seq`. This index serves it directly.
        Index(
            "ix_twin_evolution_events_twin_seq",
            "twin_id",
            "seq",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    twin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("twins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Optional back-references to the row that caused this evolution.
    # All nullable + ON DELETE SET NULL so purging an upstream row does
    # not cascade-destroy the audit trail.
    reflection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reflection_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("goals.id", ondelete="SET NULL"),
        nullable=True,
    )
    # For `profile_confirmed` only — which field changed. Named columns
    # keep the field short and bounded so the mobile UI can render it
    # without parsing arbitrary JSON.
    profile_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Short derived summary — IDs and safe metadata only. Never raw
    # content. 255 is a hard structural ceiling, not a style guideline.
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    # Sprint 10: monotonic, gap-tolerant ordering key. Drawn from the
    # dedicated `twin_evolution_events_seq` sequence at INSERT time on
    # Postgres (under a per-twin advisory lock so commit order matches
    # draw order per twin); assigned MAX(seq)+1 on SQLite in the test
    # harness, which is single-writer by construction. It is the cursor
    # the chat-time learning acknowledgement advances through — never
    # `created_at`, which is transaction_timestamp() and so is not a
    # reliable order under out-of-order commits. Always set by
    # EvolutionService.record(); no server_default here because the
    # value is assigned explicitly per dialect in the service.
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
