"""SQLAlchemy models for `twins` and `twin_profiles`.

The Twin is one-per-user in MVP. `TwinProfile` is the STABLE identity —
mutating it from an LLM response path is forbidden. The service layer only
lets the user update editable profile fields directly; profile mutations
originating from memory pass through a confirmation loop (Sprint 2+).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.conversation.models import Conversation
    from app.goal.models import Goal


class Twin(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "twins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Sprint 8: the moment a reflection run last SUCCEEDED for this twin
    # (either produced candidates or came back cleanly empty). The
    # reflection opportunity policy uses this to count "new confirmed
    # memories since the last run" and to enforce the cooldown. NULL
    # until the first successful run; the scheduler writes it inside the
    # same transaction as `ReflectionService.create_candidates` so a
    # failed run never advances it. Never touched by `/v1/reflections/run`
    # error paths. See docs/architecture/evolving-twin-loop.md.
    last_reflection_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    profile: Mapped[TwinProfile] = relationship(
        back_populates="twin",
        uselist=False,
        cascade="all, delete-orphan",
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="twin",
        cascade="all, delete-orphan",
    )
    # Sprint 4: goals cascade with the twin so deleting a user wipes their
    # goals too. GoalService never crosses twins so the FK suffices.
    goals: Mapped[list[Goal]] = relationship(
        "Goal",
        cascade="all, delete-orphan",
    )


class TwinProfile(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "twin_profiles"

    twin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("twins.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    communication_style_preset: Mapped[str] = mapped_column(
        String(32), nullable=False, default="neutral"
    )
    communication_style_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    basic_profile: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    twin: Mapped[Twin] = relationship(back_populates="profile")
