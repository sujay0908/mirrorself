"""Twin endpoints.

`POST /v1/twin` creates the Twin for the authenticated user.
`GET  /v1/twin` returns it.
`PATCH /v1/twin` applies user-authored profile edits.

Sprint 9: `GET /v1/twin/portrait` returns a deterministic "Self-Portrait"
composed from the authenticated user's own profile, confirmed memories,
active goals, and recent evolution events. No LLM is involved and no
state is mutated by a GET. See `app.twin.portrait`.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, status

from app.api.deps import (
    CurrentUser,
    DBSession,
    EvolutionServiceDep,
    GoalServiceDep,
    TwinServiceDep,
)
from app.observability.logging import get_logger
from app.twin.portrait import PortraitComposer
from app.twin.schemas import (
    TwinCreateIn,
    TwinOut,
    TwinPortraitOut,
    TwinProfilePatch,
)

router = APIRouter()
logger = get_logger(__name__)


@router.post("", response_model=TwinOut, status_code=status.HTTP_201_CREATED)
async def create_twin(
    payload: TwinCreateIn,
    user: CurrentUser,
    twins: TwinServiceDep,
) -> TwinOut:
    twin = await twins.create(user.user_id, payload)
    return TwinOut.model_validate(twin)


@router.get("", response_model=TwinOut)
async def get_twin(
    user: CurrentUser,
    twins: TwinServiceDep,
) -> TwinOut:
    twin = await twins.require_by_user(user.user_id)
    return TwinOut.model_validate(twin)


@router.patch("", response_model=TwinOut)
async def patch_twin(
    payload: TwinProfilePatch,
    user: CurrentUser,
    twins: TwinServiceDep,
) -> TwinOut:
    twin = await twins.update(user.user_id, payload)
    return TwinOut.model_validate(twin)


@router.get("/portrait", response_model=TwinPortraitOut)
async def get_twin_portrait(
    user: CurrentUser,
    twins: TwinServiceDep,
    goals: GoalServiceDep,
    evolution: EvolutionServiceDep,
    session: DBSession,
) -> TwinPortraitOut:
    """Return a deterministic self-portrait of the user's Twin.

    Composed from already-authorized data via owner-scoped services:
    `TwinService.require_by_user` → `TwinProfile`; a bounded confirmed-
    memory read; `GoalService.list_active_for_context`;
    `EvolutionService.list_for_twin`.

    No LLM is called. No row is written. GETting the portrait does
    not mutate any Twin state — asserted by `test_portrait.py`.
    """
    t0 = time.perf_counter()
    twin = await twins.require_by_user(user.user_id)
    composer = PortraitComposer(
        session,
        goal_service=goals,
        evolution_service=evolution,
    )
    portrait = await composer.compose(twin)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    # IDs, counts, timing only. No content.
    logger.info(
        "twin.portrait.returned",
        twin_id=str(twin.id),
        memory_total=portrait.memory_summary.total_count,
        memory_top_count=len(portrait.memory_summary.top_memories),
        active_goals=len(portrait.active_goals),
        recent_evolution=len(portrait.recent_evolution),
        latency_ms=latency_ms,
    )
    return TwinPortraitOut.model_validate(portrait, from_attributes=True)
