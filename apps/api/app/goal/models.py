"""SQLAlchemy models for `goals` and `goal_events`.

Design rules:

- A Goal is OWNED by a Twin (and transitively by a user). The authenticated
  user never addresses a goal by `twin_id` from the body; the service always
  resolves `twin` via `TwinService.require_by_user(current_user.user_id)`
  and only then looks up the goal under that twin.
- Status transitions are enforced by `GoalService`, not by DB CHECK alone.
  The CHECK constraint lists the valid status values; what transitions are
  legal is service-layer policy so Sprint 4+ can evolve it without a
  migration.
- `GoalEvent` is append-only. Rows record decisions (create, update,
  status-change) so the user can review what their goal did over time. No
  code path deletes GoalEvent rows.
- NO relation from Goal to Memory. Sprint 4 keeps the two orthogonal: the
  existing GOAL memory type stays, Goal entities arrive separately, and
  this module never auto-converts, auto-links, or auto-deletes anything in
  the memory tables. (Founder decisions DF2 + DF3.)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin

# MVP goal status values (also enforced by DB CHECK).
GOAL_STATUSES: tuple[str, ...] = ("active", "achieved", "abandoned", "paused")

# Priority is an integer 1..5. 1 is highest, 5 is lowest. Keeping it a plain
# integer rather than an enum lets the user drag-sort without a migration if
# the mobile UX needs finer gradations later.
GOAL_MIN_PRIORITY: int = 1
GOAL_MAX_PRIORITY: int = 5
GOAL_DEFAULT_PRIORITY: int = 3

# Event types recorded in `goal_events`.
GOAL_EVENT_TYPES: tuple[str, ...] = ("created", "updated", "status_changed")


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Goal(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','achieved','abandoned','paused')",
            name="goals_status_check",
        ),
        CheckConstraint(
            "priority >= 1 AND priority <= 5",
            name="goals_priority_check",
        ),
        Index("ix_goals_twin_status", "twin_id", "status"),
    )

    # user_id is denormalised onto the row for RLS + fast owner-scope
    # queries. The authoritative owner relationship still runs twin_id→twin.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    twin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("twins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=GOAL_DEFAULT_PRIORITY
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )
    # Timestamp of the most recent status transition. Fed into the context
    # tiebreaker (priority, then recency) deterministically.
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    events: Mapped[list[GoalEvent]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
        order_by="GoalEvent.created_at",
    )


class GoalEvent(Base, UUIDPKMixin):
    """Append-only audit record for goal lifecycle changes."""

    __tablename__ = "goal_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created','updated','status_changed')",
            name="goal_events_type_check",
        ),
    )

    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Previous and next status captured on a `status_changed` event; both
    # NULL on `created`/`updated`. Keeping them on the event (rather than
    # requiring joiners to walk history) makes read endpoints cheap.
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    goal: Mapped[Goal] = relationship(back_populates="events")
