"""
Persistent fact model. Redis keeps a fast short-term window; Postgres holds long-term facts.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # categories: personal, preference, relationship, work, dream, fear, value, goal, hobby
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # conversation id, quiz, etc.

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User")  # type: ignore[name-defined]
