"""SQLAlchemy models for `twins` and `twin_profiles`.

The Twin is one-per-user in MVP. `TwinProfile` is the STABLE identity —
mutating it from an LLM response path is forbidden. The service layer only
lets the user update editable profile fields directly; profile mutations
originating from memory pass through a confirmation loop (Sprint 2+).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.conversation.models import Conversation


class Twin(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "twins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)

    profile: Mapped[TwinProfile] = relationship(
        back_populates="twin",
        uselist=False,
        cascade="all, delete-orphan",
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="twin",
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
    basic_profile: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    twin: Mapped[Twin] = relationship(back_populates="profile")
