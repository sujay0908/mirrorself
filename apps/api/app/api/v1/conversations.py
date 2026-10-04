"""Conversation and message endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import ConversationServiceDep, CurrentUser, TwinServiceDep
from app.conversation.schemas import (
    ConversationCreateIn,
    ConversationListOut,
    ConversationOut,
    MessageIn,
    MessageListOut,
    MessageOut,
    MessagePairOut,
)

router = APIRouter()


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreateIn,
    user: CurrentUser,
    twins: TwinServiceDep,
    conversations: ConversationServiceDep,
) -> ConversationOut:
    twin = await twins.require_by_user(user.user_id)
    conv = await conversations.create(twin, payload)
    return ConversationOut.model_validate(conv)


@router.get("", response_model=ConversationListOut)
async def list_conversations(
    user: CurrentUser,
    twins: TwinServiceDep,
    conversations: ConversationServiceDep,
) -> ConversationListOut:
    twin = await twins.require_by_user(user.user_id)
    items = await conversations.list_for_twin(twin)
    return ConversationListOut(items=[ConversationOut.model_validate(c) for c in items])


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    conversations: ConversationServiceDep,
) -> ConversationOut:
    twin = await twins.require_by_user(user.user_id)
    conv = await conversations.get(twin, conversation_id)
    return ConversationOut.model_validate(conv)


@router.get("/{conversation_id}/messages", response_model=MessageListOut)
async def list_messages(
    conversation_id: uuid.UUID,
    user: CurrentUser,
    twins: TwinServiceDep,
    conversations: ConversationServiceDep,
) -> MessageListOut:
    twin = await twins.require_by_user(user.user_id)
    msgs = await conversations.list_messages(twin, conversation_id)
    return MessageListOut(items=[MessageOut.model_validate(m) for m in msgs])


@router.post(
    "/{conversation_id}/messages",
    response_model=MessagePairOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    conversation_id: uuid.UUID,
    payload: MessageIn,
    user: CurrentUser,
    twins: TwinServiceDep,
    conversations: ConversationServiceDep,
) -> MessagePairOut:
    twin = await twins.require_by_user(user.user_id)
    user_msg, twin_msg = await conversations.post_message(twin, conversation_id, payload.content)
    return MessagePairOut(
        user_message=MessageOut.model_validate(user_msg),
        twin_message=MessageOut.model_validate(twin_msg),
    )
