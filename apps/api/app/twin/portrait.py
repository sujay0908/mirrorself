"""Twin Self-Portrait composition (Sprint 9).

A DETERMINISTIC view of what the Twin currently knows about the user.
No LLM. No narrative generation. No new persistence. No new mutation
path. The portrait is a pure read-aggregator over the owner-scoped
services that already exist:

- `TwinProfile` → "How I speak to you"
- confirmed, non-superseded `Memory` rows → "What I remember about you"
- active `Goal` rows (via `GoalService.list_active_for_context`) →
  "What you're working on"
- newest `TwinEvolutionEvent` rows (via
  `EvolutionService.list_for_twin`) → "What I've noticed recently"

Design rules enforced here:

- **No side effects.** The composer only reads. It never writes to
  the DB, never calls an LLM, never emits a reflection, never
  creates an evolution event, never updates a profile. GETting the
  portrait does not change any Twin state.
- **Owner-scoped by caller.** The caller resolves the `Twin` from the
  authenticated user via `TwinService.require_by_user(user_id)` and
  passes the ORM instance in. No `twin_id` from a request body is
  ever accepted.
- **Privacy-safe truncation.** Memory snippets are truncated at a
  code-point boundary (`str` slicing is already code-point-aware;
  the snippet length is a logical character count, not a byte count),
  then an ellipsis is appended when the original overflowed.
- **No logs with content.** The composer never logs memory content,
  goal content, profile content, or evolution summaries. The
  endpoint logs IDs + counts + timing only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evolution.service import EvolutionService
from app.goal.service import GoalService
from app.memory.models import MEMORY_TYPES, Memory
from app.twin.models import Twin

# Caps shipped in Sprint 9. Kept here as module-level constants so a
# future tightening lands in one place and the tests pin the shipped
# values.
MEMORY_SNIPPET_MAX_CHARS: int = 240
TOP_MEMORIES_LIMIT: int = 5
ACTIVE_GOALS_LIMIT: int = 5
RECENT_EVOLUTION_LIMIT: int = 5


# ----------------------------------------------------------------
# Portrait-local return shapes.
#
# These are intentionally separate dataclasses rather than the service-
# facing ORM/schema types. The portrait exposes a strict subset — e.g.
# a memory snippet, not the full MemoryOut graph. Keeping the
# dataclasses local to this module avoids widening any existing
# service response.
# ----------------------------------------------------------------


@dataclass(slots=True)
class PortraitProfile:
    display_name: str
    style_preset: str
    style_notes: str | None
    basic_profile: dict[str, Any]


@dataclass(slots=True)
class PortraitMemory:
    id: uuid.UUID
    type: str
    importance: float
    snippet: str


@dataclass(slots=True)
class PortraitMemorySummary:
    total_count: int
    counts_by_type: dict[str, int]
    top_memories: list[PortraitMemory]


@dataclass(slots=True)
class PortraitGoal:
    id: uuid.UUID
    title: str
    description: str | None
    priority: int
    target_date: datetime | None


@dataclass(slots=True)
class PortraitEvolution:
    id: uuid.UUID
    event_type: str
    summary: str
    created_at: datetime
    lead: str  # "learned" | "acknowledged"


@dataclass(slots=True)
class TwinPortrait:
    profile: PortraitProfile
    memory_summary: PortraitMemorySummary
    active_goals: list[PortraitGoal]
    recent_evolution: list[PortraitEvolution]


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------


def _truncate_snippet(content: str, limit: int = MEMORY_SNIPPET_MAX_CHARS) -> str:
    """Truncate a memory snippet to at most `limit` characters.

    Python `str` slicing is code-point-aware, so slicing at index
    `limit` never splits a Unicode code point. We leave combining
    sequences and surrogate pairs to the renderer — the backend
    guarantees a character-bounded, not grapheme-bounded, snippet,
    which is the privacy-safe bound we need.
    """
    if content is None:
        return ""
    stripped = content.strip()
    if len(stripped) <= limit:
        return stripped
    # Leave room for the ellipsis within the structural cap.
    return stripped[: limit - 1] + "…"


def _evolution_lead(event_type: str) -> str:
    """Map Sprint 8 evolution event types to the user-facing distinction.

    - `insight_acknowledged` → "acknowledged" (Sprint 7 Decision #1:
      insight confirmation is acknowledgement, NOT identity mutation).
    - everything else → "learned" (a durable change actually took
      effect).

    The mobile layer uses the lead to pick its one-line header
    ("Your Twin learned..." vs "You acknowledged..."). The lead is
    computed server-side so the UI never diverges from the semantic
    the apply dispatcher recorded.
    """
    if event_type == "insight_acknowledged":
        return "acknowledged"
    return "learned"


# ----------------------------------------------------------------
# Composer
# ----------------------------------------------------------------


class PortraitComposer:
    """Pure read-aggregator over the owner-scoped data the user owns.

    Not a FastAPI dependency class — it is instantiated per request
    with a session + the already-resolved `Twin`. The endpoint handler
    builds it, calls `compose()`, serialises the result, and discards
    the instance.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        goal_service: GoalService,
        evolution_service: EvolutionService,
    ) -> None:
        self._session = session
        self._goal_service = goal_service
        self._evolution_service = evolution_service

    async def compose(self, twin: Twin) -> TwinPortrait:
        profile = self._compose_profile(twin)
        memory_summary = await self._compose_memory_summary(twin)
        active_goals = await self._compose_active_goals(twin)
        recent_evolution = await self._compose_recent_evolution(twin)
        return TwinPortrait(
            profile=profile,
            memory_summary=memory_summary,
            active_goals=active_goals,
            recent_evolution=recent_evolution,
        )

    def _compose_profile(self, twin: Twin) -> PortraitProfile:
        profile = twin.profile
        return PortraitProfile(
            display_name=twin.display_name,
            style_preset=profile.communication_style_preset,
            style_notes=profile.communication_style_notes,
            # Return a shallow copy so a downstream renderer cannot
            # mutate the ORM-attached dict.
            basic_profile=dict(profile.basic_profile or {}),
        )

    async def _compose_memory_summary(self, twin: Twin) -> PortraitMemorySummary:
        """Query confirmed, non-superseded memories only.

        Three queries:
        1. total count.
        2. count-by-type (one GROUP BY).
        3. top-N by importance (ORDER BY importance DESC + id ASC for
           deterministic tie-breaking).

        Rejected memory candidates have no `memories` row so they
        cannot leak. Pending candidates also have no `memories` row.
        Superseded rows are filtered explicitly.
        """
        base_where = (
            Memory.twin_id == twin.id,
            Memory.user_id == twin.user_id,
            Memory.user_confirmed.is_(True),
            Memory.superseded_by_memory_id.is_(None),
        )

        total_count = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(Memory).where(*base_where)
                )
            ).scalar_one()
        )

        counts_stmt = select(Memory.type, func.count()).where(*base_where).group_by(Memory.type)
        counts_rows = (await self._session.execute(counts_stmt)).all()
        # Initialise every known type to 0 so the mobile UI can render
        # a stable row for each.
        counts_by_type: dict[str, int] = dict.fromkeys(MEMORY_TYPES, 0)
        for mem_type, n in counts_rows:
            counts_by_type[mem_type] = int(n)

        top_stmt = (
            select(Memory)
            .where(*base_where)
            .order_by(Memory.importance.desc(), Memory.id.asc())
            .limit(TOP_MEMORIES_LIMIT)
        )
        top_rows = (await self._session.execute(top_stmt)).scalars().all()
        top_memories = [
            PortraitMemory(
                id=row.id,
                type=row.type,
                importance=row.importance,
                snippet=_truncate_snippet(row.content),
            )
            for row in top_rows
        ]
        return PortraitMemorySummary(
            total_count=total_count,
            counts_by_type=counts_by_type,
            top_memories=top_memories,
        )

    async def _compose_active_goals(self, twin: Twin) -> list[PortraitGoal]:
        """Delegate to the Sprint 4 goal service — no duplicate SQL."""
        goals = await self._goal_service.list_active_for_context(twin, limit=ACTIVE_GOALS_LIMIT)
        return [
            PortraitGoal(
                id=g.id,
                title=g.title,
                description=g.description,
                priority=g.priority,
                target_date=g.target_date,
            )
            for g in goals
        ]

    async def _compose_recent_evolution(self, twin: Twin) -> list[PortraitEvolution]:
        """Delegate to the Sprint 8 evolution service — no duplicate SQL.

        `list_for_twin` returns newest-first already. The composer
        attaches the Sprint-8 user-facing `lead` on each row.
        """
        rows = await self._evolution_service.list_for_twin(twin, limit=RECENT_EVOLUTION_LIMIT)
        return [
            PortraitEvolution(
                id=r.id,
                event_type=r.event_type,
                summary=r.summary,
                created_at=r.created_at,
                lead=_evolution_lead(r.event_type),
            )
            for r in rows
        ]
