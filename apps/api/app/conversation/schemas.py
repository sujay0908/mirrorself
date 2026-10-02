"""Pydantic schemas for conversation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MessageRole = Literal["user", "twin", "system"]


class ConversationCreateIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    twin_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    llm_provider: str | None
    llm_model: str | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


class MessagePairOut(BaseModel):
    """The response of `POST /v1/conversations/{id}/messages`: both turns."""

    user_message: MessageOut
    twin_message: MessageOut


class ConversationListOut(BaseModel):
    items: list[ConversationOut]


class MessageListOut(BaseModel):
    items: list[MessageOut]
