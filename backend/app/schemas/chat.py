"""
Chat-related schemas.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[int] = None
    audio_base64: Optional[str] = None  # if user spoke


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    detected_emotion: Optional[str] = None
    response_tone: Optional[str] = None
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: int
    user_message: MessageOut
    assistant_message: MessageOut
    new_facts: list[str] = []


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]
