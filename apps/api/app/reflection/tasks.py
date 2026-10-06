"""Background task for scheduled reflection runs (Sprint 8).

Runs AFTER the chat response is persisted and returned. Opens its own
DB session so it does not share the request's unit of work. Never
raises back to the chat path — if the scheduler itself blows up, we
swallow the exception and log `reflection.schedule.failed`.

The user-facing `/v1/reflections/run` endpoint is unaffected — it
remains the manual override and runs in the request's own session.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.interface import LLMProvider
from app.observability.logging import get_logger
from app.reflection.extractor import ReflectionExtractor
from app.reflection.scheduler import OpportunityPolicy, ReflectionScheduler
from app.reflection.service import ReflectionService
from app.twin.service import TwinService

logger = get_logger(__name__)


async def scheduled_reflection_task(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    llm_provider: LLMProvider,
    llm_model: str,
    user_id: uuid.UUID,
    twin_id: uuid.UUID,
    settings: Settings,
) -> None:
    """Run `ReflectionScheduler.maybe_run(twin)` once, in a fresh session.

    All exceptions are logged and swallowed. The chat response has
    already been persisted when this task is awaited, so the only risk
    of a bubble-up would be a FastAPI background-task warning in the
    server logs.
    """
    log_ctx = {"twin_id": str(twin_id)}
    try:
        async with sessionmaker() as session:
            twin_service = TwinService(session)
            twin = await twin_service.require_by_user(user_id)
            extractor = ReflectionExtractor(llm_provider, llm_model)
            reflection_service = ReflectionService(session)
            policy = OpportunityPolicy.from_settings(settings)
            scheduler = ReflectionScheduler(
                session,
                extractor=extractor,
                reflection_service=reflection_service,
                policy=policy,
            )
            await scheduler.maybe_run(twin)
    except Exception as exc:
        logger.warning(
            "reflection.schedule.failed",
            error=type(exc).__name__,
            **log_ctx,
        )
