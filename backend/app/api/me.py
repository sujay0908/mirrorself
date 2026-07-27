"""
User profile and conversation history endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.conversation import Conversation, Message
from app.models.fact import Fact
from app.models.user import User
from app.schemas.chat import ConversationDetail, ConversationSummary
from app.schemas.user import UserPrivate, UserUpdate
from app.services.response_mapper import map_message, map_user_private

router = APIRouter(prefix="/me", tags=["me"])


@router.patch("", response_model=UserPrivate)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPrivate:
    if payload.display_name is not None:
        current_user.display_name = payload.display_name
    if payload.bio is not None:
        current_user.bio = payload.bio
    if payload.is_public is not None:
        current_user.is_public = payload.is_public
    if payload.personality is not None:
        current_user.personality = payload.personality.model_dump()
    await db.commit()
    await db.refresh(current_user)
    return await map_user_private(current_user)


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationSummary]:
    rows = (
        await db.execute(
            select(
                Conversation,
                func.count(Message.id).label("msg_count"),
            )
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id == current_user.id)
            .group_by(Conversation.id)
            .order_by(Conversation.updated_at.desc())
        )
    ).all()
    return [
        ConversationSummary(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=count,
        )
        for conv, count in rows
    ]


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    msgs = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
        )
    ).scalars().all()
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[await map_message(msg) for msg in msgs],
    )


@router.get("/facts")
async def list_facts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Fact).where(Fact.user_id == current_user.id).order_by(Fact.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": f.id,
            "category": f.category,
            "content": f.content,
            "confidence": f.confidence,
            "created_at": f.created_at.isoformat(),
        }
        for f in rows
    ]


@router.delete("/facts/{fact_id}")
async def delete_fact(
    fact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fact = (
        await db.execute(
            select(Fact).where(Fact.id == fact_id, Fact.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if not fact:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fact not found")
    await db.delete(fact)
    await db.commit()
    return {"ok": True}
