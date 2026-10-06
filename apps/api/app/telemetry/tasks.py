"""Background task that writes a single intent telemetry row.

Runs after the chat response has been persisted and returned. Opens its
own session so it does not share the request's unit of work. Never
raises back to the chat path.

The function signature INTENTIONALLY takes already-safe fields only —
not the raw user message, not the IntentResult object (which could grow
new sensitive fields in a future sprint). Callers must call
`length_bucket(user_message)` BEFORE enqueueing so the raw text never
reaches this coroutine.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.observability.logging import get_logger
from app.telemetry.service import IntentTelemetryService

logger = get_logger(__name__)


async def record_intent_telemetry_task(
    *,
    sessionmaker: async_sessionmaker,  # type: ignore[type-arg]
    user_id: uuid.UUID,
    twin_id: uuid.UUID,
    intent: str,
    confidence: float,
    reason: str,
    detector_name: str,
    latency_ms: int,
    message_length_bucket: str,
) -> None:
    log_ctx = {
        "twin_id": str(twin_id),
        "intent": intent,
    }
    try:
        async with sessionmaker() as session:
            service = IntentTelemetryService(session)
            await service.record(
                user_id=user_id,
                twin_id=twin_id,
                intent=intent,
                confidence=confidence,
                reason=reason,
                detector_name=detector_name,
                latency_ms=latency_ms,
                message_length_bucket=message_length_bucket,
            )
    except Exception as exc:
        logger.warning(
            "intent.telemetry.failed",
            error=type(exc).__name__,
            **log_ctx,
        )
