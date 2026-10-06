"""ORM for `intent_telemetry_events` (Sprint 8).

Privacy contract (asserted by the Sprint 8 sentinel test):

- No message content is stored. The row carries ONLY the intent label,
  the confidence band, the detector's `reason` tag (always of the form
  `kind:tag` — e.g. `phrase:plan`, `fallback:short_message`, never free
  text), the detector name, the latency, and a bucket for the message
  length. Reading every column of a row never surfaces a user message.
- `message_length_bucket` is `short|medium|long`. Thresholds live in
  `app.telemetry.service`; writers never store the exact character count
  or the raw text.
- The table does NOT reference a message id. Linking telemetry back to
  a conversation message would reintroduce the content-recovery surface
  the privacy contract is here to prevent.

Lifecycle:

- Written by a `TaskRunner` background task AFTER the chat response is
  persisted. Chat latency is unaffected and chat success does not
  depend on telemetry success.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPKMixin

MESSAGE_LENGTH_BUCKETS: tuple[str, ...] = ("short", "medium", "long")


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class IntentTelemetryEvent(Base, UUIDPKMixin):
    __tablename__ = "intent_telemetry_events"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="intent_telemetry_confidence_check",
        ),
        CheckConstraint(
            "message_length_bucket IN ('short','medium','long')",
            name="intent_telemetry_bucket_check",
        ),
        Index(
            "ix_intent_telemetry_twin_created",
            "twin_id",
            "created_at",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    twin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("twins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Intent as a plain enum value (string). We DO NOT use a CHECK IN
    # (…) here because a future expansion of `Intent` should be
    # transparent to telemetry.
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # The detector's safe reason tag — always `kind:tag`. See
    # `app.conversation.intent.IntentResult.reason`. Capped at 64
    # characters to prevent future callers from stuffing content here.
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    detector_name: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_length_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
