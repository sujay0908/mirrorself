"""Conversation and message endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.deps import ConversationServiceDep, CurrentUser, TwinServiceDep, rate_limit
from app.conversation.schemas import (
    ConversationCreateIn,
    ConversationListOut,
    ConversationOut,
    MessageIn,
    MessageListOut,
    MessageOut,
    MessagePairOut,
)
from app.conversation.service import (
    CONVERSATION_LIST_DEFAULT,
    CONVERSATION_LIST_MAX,
    MESSAGE_LIST_DEFAULT,
    MESSAGE_LIST_MAX,
)

router = APIRouter()

# Client-chosen, opaque, and stored. Bounded and restricted to a safe
# alphabet so it cannot carry anything but an identifier.
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Repeat a send with the same key to get the original "
        "exchange back instead of a duplicate turn.",
    ),
]


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
    limit: int = Query(default=CONVERSATION_LIST_DEFAULT, ge=1, le=CONVERSATION_LIST_MAX),
    offset: int = Query(default=0, ge=0),
) -> ConversationListOut:
    twin = await twins.require_by_user(user.user_id)
    items = await conversations.list_for_twin(twin, limit=limit, offset=offset)
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
    limit: int = Query(default=MESSAGE_LIST_DEFAULT, ge=1, le=MESSAGE_LIST_MAX),
    before: Annotated[
        uuid.UUID | None,
        Query(description="A message id from a previous page; returns the messages older than it."),
    ] = None,
) -> MessageListOut:
    twin = await twins.require_by_user(user.user_id)
    msgs = await conversations.list_messages(twin, conversation_id, limit=limit, before=before)
    return MessageListOut(items=[MessageOut.model_validate(m) for m in msgs])


@router.post(
    "/{conversation_id}/messages",
    response_model=MessagePairOut,
    status_code=status.HTTP_201_CREATED,
    # Each call is a model request that costs money; this is tighter than
    # the general per-user limit.
    dependencies=[Depends(rate_limit("chat"))],
)
async def post_message(
    conversation_id: uuid.UUID,
    payload: MessageIn,
    response: Response,
    user: CurrentUser,
    twins: TwinServiceDep,
    conversations: ConversationServiceDep,
    idempotency_key: IdempotencyKey = None,
) -> MessagePairOut:
    twin = await twins.require_by_user(user.user_id)
    user_msg, twin_msg, replayed = await conversations.post_message(
        twin,
        conversation_id,
        payload.content,
        client_request_id=idempotency_key,
    )
    if replayed:
        # Same body as the original response; nothing new was created.
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return MessagePairOut(
        user_message=MessageOut.model_validate(user_msg),
        twin_message=MessageOut.model_validate(twin_msg),
    )
