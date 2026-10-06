"""IntentTelemetryService — write-only service for the intent telemetry stream.

Public surface is intentionally small: a `record(...)` method that
accepts the already-safe fields of an `IntentResult` plus some derived
metadata, and writes a row.

Never takes the raw user message. The length bucket is pre-computed by
`length_bucket(text)` so callers hand this service a `str` enum value,
never the content.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.logging import get_logger
from app.telemetry.models import IntentTelemetryEvent

logger = get_logger(__name__)

# Thresholds in characters (not words — tokeniser-independent and
# cheaper). Values picked to match the Sprint-6 "fallback:short_message"
# TALK heuristic without leaking its exact wording to callers.
_SHORT_MAX_CHARS: int = 40
_MEDIUM_MAX_CHARS: int = 240


def length_bucket(text: str) -> str:
    """Classify a message length into `short|medium|long`.

    Pure, deterministic. Thresholds are character counts of the
    stripped text; the raw text is NOT retained after this call.
    """
    n = len(text.strip())
    if n <= _SHORT_MAX_CHARS:
        return "short"
    if n <= _MEDIUM_MAX_CHARS:
        return "medium"
    return "long"


class IntentTelemetryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        user_id: uuid.UUID,
        twin_id: uuid.UUID,
        intent: str,
        confidence: float,
        reason: str,
        detector_name: str,
        latency_ms: int,
        message_length_bucket: str,
    ) -> IntentTelemetryEvent:
        row = IntentTelemetryEvent(
            user_id=user_id,
            twin_id=twin_id,
            intent=intent,
            confidence=confidence,
            # Cap defensively — the DB column caps at 64 anyway, but
            # truncating here keeps logs clean.
            reason=reason[:64],
            detector_name=detector_name[:64],
            latency_ms=max(0, int(latency_ms)),
            message_length_bucket=message_length_bucket,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.commit()
        logger.info(
            "intent.detected",
            twin_id=str(twin_id),
            intent=intent,
            confidence=confidence,
            reason=reason[:64],
            detector_name=detector_name[:64],
            latency_ms=max(0, int(latency_ms)),
            message_length_bucket=message_length_bucket,
        )
        return row
