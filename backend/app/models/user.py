"""
User ORM model. Holds onboarding data, voice + face asset paths, and twin status.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Auth
    supabase_user_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Profile
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Onboarding
    is_onboarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Supabase Storage object paths (e.g., "user_123/photo.jpg") or signed URLs
    face_photo_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    voice_sample_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Twin / avatar
    voice_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    # Supabase Storage object path for avatar video (e.g., "user_123/avatar.mp4")
    avatar_video_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    twin_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )  # pending | processing | ready | failed

    # Personality profile (from quiz)
    personality: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Shape:
    # {
    #   "values": [...], "communication_style": "...", "humor": "...",
    #   "fears": [...], "dreams": [...]
    # }

    # Usage
    conversation_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    conversations: Mapped[list["Conversation"]] = relationship(  # type: ignore[name-defined]
        "Conversation", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username}>"
