"""
Public profile endpoints. /u/{username} is the public face of someone's twin.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.user import UserPublic
from app.services.chat_service import chat_service

router = APIRouter(prefix="/u", tags=["public"])


@router.get("/{username}", response_model=UserPublic)
async def get_public_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
    visitor: User | None = Depends(get_optional_user),
) -> UserPublic:
    user = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if not user or not user.is_public:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Twin not found or private")
    if user.twin_status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "This twin is still being generated.")
    return UserPublic.model_validate(user)


@router.post("/{username}/chat", response_model=ChatResponse)
async def chat_with_twin(
    username: str,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    visitor: User | None = Depends(get_optional_user),
) -> ChatResponse:
    user = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if not user or not user.is_public:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Twin not found or private")
    if user.twin_status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "This twin is still being generated.")
    return await chat_service.chat(
        db=db, user=user, message=payload.message,
        conversation_id=payload.conversation_id, twin_mode=True,
    )
