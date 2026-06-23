"""
Chat-related schemas.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


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
    # Store Supabase Storage object paths, but expose as URLs
    audio_path: Optional[str] = Field(None, alias="audio_url", exclude=True)
    video_path: Optional[str] = Field(None, alias="video_url", exclude=True)
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    created_at: datetime

    @field_serializer("audio_url")
    def serialize_audio_url(self, value: Optional[str]) -> Optional[str]:
        """Return audio_path as audio_url (already object path from storage)."""
        return self.audio_path

    @field_serializer("video_url")
    def serialize_video_url(self, value: Optional[str]) -> Optional[str]:
        """Return video_path as video_url (already object path from storage)."""
        return self.video_path


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
