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

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.evolution.locks import acquire_twin_evolution_lock
from app.evolution.models import EVOLUTION_EVENT_TYPES, TwinEvolutionEvent
from app.observability.logging import get_logger
from app.twin.models import Twin

logger = get_logger(__name__)


_SUMMARY_MAX = 255

# Name of the Postgres sequence created by migration 0007. The service
# draws from it explicitly (rather than via a column server_default) so
# the draw happens while the per-twin advisory lock is held, pinning
# commit order to seq order per twin.
_SEQ_NAME = "twin_evolution_events_seq"


async def _next_seq(session: AsyncSession, twin_id: uuid.UUID) -> int:
    """Assign the next monotonic `seq` for an evolution-event insert.

    PostgreSQL: take the per-twin evolution advisory lock (so no other
    writer for this twin can draw a seq until we commit), then draw from
    the dedicated sequence. The lock makes commit order match draw order
    per twin, which is what keeps the chat acknowledgement cursor from
    ever stepping over an event that becomes visible out of draw order.

    SQLite (test harness): single-writer by construction, so a plain
    MAX(seq)+1 is deterministic and monotonic. No advisory lock exists.
    """
    bind = session.bind
    if bind is not None and bind.dialect.name == "postgresql":
        await acquire_twin_evolution_lock(session, twin_id)
        result = await session.execute(text(f"SELECT nextval('{_SEQ_NAME}')"))
        return int(result.scalar_one())
    current_max = (
        await session.execute(
            select(func.coalesce(func.max(TwinEvolutionEvent.seq), 0))
        )
    ).scalar_one()
    return int(current_max) + 1


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
        # Sprint 10: draw the monotonic `seq` (under the per-twin
        # advisory lock on Postgres) before building the row, so commit
        # order matches seq order per twin.
        seq = await _next_seq(self._session, twin.id)
        row = TwinEvolutionEvent(
            user_id=twin.user_id,
            twin_id=twin.id,
            event_type=event_type,
            reflection_id=reflection_id,
            memory_id=memory_id,
            goal_id=goal_id,
            profile_field=profile_field,
            summary=summary,
            seq=seq,
        )
        self._session.add(row)
        await self._session.flush()
        logger.info(
            "twin.evolution.created",
            twin_id=str(twin.id),
            event_id=str(row.id),
            seq=row.seq,
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

    async def unacknowledged_for_twin(
        self,
        twin: Twin,
        *,
        limit: int,
    ) -> Sequence[TwinEvolutionEvent]:
        """Oldest-first slice of evolution events not yet acknowledged.

        "Not yet acknowledged" = `seq` strictly greater than the twin's
        `last_acknowledged_evolution_seq` cursor. Ordered by `seq`
        ascending so the caller surfaces events in the order they were
        learned and advances the cursor to the slice's max seq. Owner-
        scoped by `(twin_id, user_id)`.
        """
        stmt = (
            select(TwinEvolutionEvent)
            .where(
                TwinEvolutionEvent.twin_id == twin.id,
                TwinEvolutionEvent.user_id == twin.user_id,
                TwinEvolutionEvent.seq > twin.last_acknowledged_evolution_seq,
            )
            .order_by(TwinEvolutionEvent.seq.asc())
            .limit(limit)
        )
        return (await self._session.execute(stmt)).scalars().all()
