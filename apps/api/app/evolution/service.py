"""EvolutionService — append-only writer + owner-scoped reader (Sprint 8).

This service does not take an opinion on which event types mean what —
it simply persists what callers hand it. The founder-decision contract
("Only confirmed/applied changes represent actual Twin evolution.
Rejected reflection candidates must NOT create evolution events.") is
enforced at the call sites in `ReflectionService._apply` and
`MemoryService.confirm_candidate`, which only invoke `record()` after
their respective durable write has committed.

Privacy contract (checked by `test_evolution_privacy_sentinel`):

- `summary` lands verbatim in the row. Callers compose it from stored
  IDs and safe metadata only — never user message, memory, goal, or
  profile text.
- The service itself logs IDs and `event_type` only.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evolution.models import EVOLUTION_EVENT_TYPES, TwinEvolutionEvent
from app.observability.logging import get_logger
from app.twin.models import Twin

logger = get_logger(__name__)


_SUMMARY_MAX = 255


class EvolutionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        twin: Twin,
        *,
        event_type: str,
        summary: str,
        reflection_id: uuid.UUID | None = None,
        memory_id: uuid.UUID | None = None,
        goal_id: uuid.UUID | None = None,
        profile_field: str | None = None,
    ) -> TwinEvolutionEvent:
        if event_type not in EVOLUTION_EVENT_TYPES:
            raise ValueError(f"Unknown evolution event type: {event_type!r}")
        # Hard structural cap. Callers compose a short IDs/metadata-only
        # string; truncation here is a last line of defence, not a style
        # choice — a longer summary almost certainly leaked content.
        if len(summary) > _SUMMARY_MAX:
            summary = summary[: _SUMMARY_MAX - 1] + "…"
        row = TwinEvolutionEvent(
            user_id=twin.user_id,
            twin_id=twin.id,
            event_type=event_type,
            reflection_id=reflection_id,
            memory_id=memory_id,
            goal_id=goal_id,
            profile_field=profile_field,
            summary=summary,
        )
        self._session.add(row)
        await self._session.flush()
        logger.info(
            "twin.evolution.created",
            twin_id=str(twin.id),
            event_id=str(row.id),
            event_type=event_type,
            reflection_id=str(reflection_id) if reflection_id else None,
            memory_id=str(memory_id) if memory_id else None,
            goal_id=str(goal_id) if goal_id else None,
            profile_field=profile_field,
        )
        return row

    async def list_for_twin(
        self,
        twin: Twin,
        *,
        limit: int = 50,
    ) -> Sequence[TwinEvolutionEvent]:
        """Newest-first list of evolution events for the owning twin."""
        stmt = (
            select(TwinEvolutionEvent)
            .where(
                TwinEvolutionEvent.twin_id == twin.id,
                TwinEvolutionEvent.user_id == twin.user_id,
            )
            .order_by(
                TwinEvolutionEvent.created_at.desc(),
                TwinEvolutionEvent.id.asc(),
            )
            .limit(limit)
        )
        return (await self._session.execute(stmt)).scalars().all()
