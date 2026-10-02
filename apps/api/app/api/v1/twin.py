"""Twin endpoints.

`POST /v1/twin` creates the Twin for the authenticated user.
`GET  /v1/twin` returns it.
`PATCH /v1/twin` applies user-authored profile edits.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, TwinServiceDep
from app.twin.schemas import TwinCreateIn, TwinOut, TwinProfilePatch

router = APIRouter()


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
