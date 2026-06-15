"""
Chat endpoints (own twin and public twin).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    return await chat_service.chat(
        db=db, user=current_user, message=payload.message, conversation_id=payload.conversation_id
    )
