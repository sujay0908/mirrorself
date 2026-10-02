"""Twin domain service.

Rules:
- One Twin per user.
- Profile edits from THIS service are user-driven (via PATCH). No code path
  in the LLM response pipeline may call `update_profile` — that gate lives
  in Sprint 2's reflection confirmation flow.
- `user_id` is always derived from the authenticated request, never the body.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.observability.logging import get_logger
from app.twin.errors import TwinAlreadyExistsError, TwinNotFoundError
from app.twin.models import Twin, TwinProfile
from app.twin.schemas import TwinCreateIn, TwinProfilePatch

logger = get_logger(__name__)


class TwinService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user(self, user_id: uuid.UUID) -> Twin | None:
        stmt = (
            select(Twin)
            .where(Twin.user_id == user_id)
            .options(selectinload(Twin.profile))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def require_by_user(self, user_id: uuid.UUID) -> Twin:
        twin = await self.get_by_user(user_id)
        if twin is None:
            raise TwinNotFoundError("You do not have a Twin yet.")
        return twin

    async def create(self, user_id: uuid.UUID, payload: TwinCreateIn) -> Twin:
        existing = await self.get_by_user(user_id)
        if existing is not None:
            raise TwinAlreadyExistsError(
                "You already have a Twin. One Twin per user in MVP.",
                details={"twin_id": str(existing.id)},
            )

        twin = Twin(user_id=user_id, display_name=payload.name)
        twin.profile = TwinProfile(
            communication_style_preset=payload.communication_style,
            basic_profile=payload.basic_profile,
        )
        self._session.add(twin)
        await self._session.flush()
        await self._session.commit()
        await self._session.refresh(twin, attribute_names=["profile"])
        logger.info("twin.created", twin_id=str(twin.id), user_id=str(user_id))
        return twin

    async def update(self, user_id: uuid.UUID, patch: TwinProfilePatch) -> Twin:
        twin = await self.require_by_user(user_id)
        # User-initiated edits only. The LLM pipeline must not call this.
        if patch.display_name is not None:
            twin.display_name = patch.display_name
        if patch.communication_style_preset is not None:
            twin.profile.communication_style_preset = patch.communication_style_preset
        if patch.communication_style_notes is not None:
            twin.profile.communication_style_notes = patch.communication_style_notes
        if patch.basic_profile is not None:
            twin.profile.basic_profile = patch.basic_profile
        await self._session.commit()
        await self._session.refresh(twin, attribute_names=["profile"])
        logger.info("twin.updated", twin_id=str(twin.id))
        return twin
