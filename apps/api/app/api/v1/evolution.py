"""/v1/twin/evolution — append-only read of Twin evolution events (Sprint 8).

Rows are written by the services themselves (`MemoryService.confirm_candidate`
for `memory_learned`; `ReflectionService._record_evolution_for` for the
other four types). This endpoint only reads.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, EvolutionServiceDep, TwinServiceDep
from app.evolution.schemas import EvolutionEventOut, EvolutionListOut

router = APIRouter()


@router.get("", response_model=EvolutionListOut)
async def list_evolution(
    user: CurrentUser,
    twins: TwinServiceDep,
    evolution: EvolutionServiceDep,
    limit: int = 50,
) -> EvolutionListOut:
    twin = await twins.require_by_user(user.user_id)
    rows = await evolution.list_for_twin(twin, limit=max(1, min(limit, 100)))
    return EvolutionListOut(
        items=[EvolutionEventOut.model_validate(r) for r in rows],
    )
