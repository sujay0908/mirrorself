"""/v1/goals endpoints.

- `GET  /v1/goals` list, optionally filtered by `status`.
- `POST /v1/goals` create a new goal (status defaults to `active`).
- `GET  /v1/goals/{id}` fetch one.
- `PATCH /v1/goals/{id}` edit fields and/or change status.
- `GET  /v1/goals/{id}/events` list the append-only audit trail.

Every endpoint resolves the authenticated user's Twin through
`TwinService.require_by_user` and then addresses the goal through that
Twin. A goal id from another user resolves to 404, not 403, to avoid
leaking existence.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, GoalServiceDep, TwinServiceDep
from app.goal.schemas import (
    GoalCreateIn,
    GoalEventOut,
    GoalEventsOut,
    GoalListOut,
    GoalOut,
    GoalStatus,
    GoalUpdateIn,
)

router = APIRouter()

# Module-level default for `status` query — using `Query(...)` inline
# triggers ruff B008. Declared once here and consumed via Annotated so the
# intent is still obvious at the call site.
_STATUS_QUERY = Query(default=None, alias="status")


@router.get("", response_model=GoalListOut)
async def list_goals(
    user: CurrentUser,
    twins: TwinServiceDep,
    goals: GoalServiceDep,
    status_filter: GoalStatus | None = _STATUS_QUERY,
) -> GoalListOut:
    twin = await twins.require_by_user(user.user_id)
    items = await goals.list_for_twin(twin, status=status_filter)
    return GoalListOut(items=[GoalOut.model_validate(g) for g in items])


@router.post("", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
async def create_goal(
    payload: GoalCreateIn,
    user: CurrentUser,
    twins: TwinServiceDep,
    goals: GoalServiceDep,
) -> GoalOut:
    twin = await twins.require_by_user(user.user_id)
    goal = await goals.create(twin, payload)
    return GoalOut.model_validate(goal)


@router.get("/{goal_id}", response_model=GoalOut)
async def get_goal(
    goal_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    goals: GoalServiceDep,
) -> GoalOut:
    twin = await twins.require_by_user(user.user_id)
    goal = await goals.get(twin, goal_id)
    return GoalOut.model_validate(goal)


@router.patch("/{goal_id}", response_model=GoalOut)
async def patch_goal(
    goal_id: uuid.UUID,
    payload: GoalUpdateIn,
    user: CurrentUser,
    twins: TwinServiceDep,
    goals: GoalServiceDep,
) -> GoalOut:
    twin = await twins.require_by_user(user.user_id)
    goal = await goals.update(twin, goal_id, payload)
    return GoalOut.model_validate(goal)


@router.get("/{goal_id}/events", response_model=GoalEventsOut)
async def list_goal_events(
    goal_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    goals: GoalServiceDep,
) -> GoalEventsOut:
    twin = await twins.require_by_user(user.user_id)
    events = await goals.list_events(twin, goal_id)
    return GoalEventsOut(items=[GoalEventOut.model_validate(e) for e in events])
