"""Pydantic request/response schemas for the Twin endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CommunicationStylePreset = Literal["neutral", "terse", "warm", "analytical"]


class TwinProfileIn(BaseModel):
    communication_style_preset: CommunicationStylePreset = "neutral"
    communication_style_notes: str | None = Field(default=None, max_length=2000)
    basic_profile: dict[str, Any] = Field(default_factory=dict)


class TwinCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    communication_style: CommunicationStylePreset = "neutral"
    basic_profile: dict[str, Any] = Field(default_factory=dict)


class TwinProfilePatch(BaseModel):
    """PATCH body for /v1/twin. All fields optional; missing = unchanged."""

    communication_style_preset: CommunicationStylePreset | None = None
    communication_style_notes: str | None = Field(default=None, max_length=2000)
    basic_profile: dict[str, Any] | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=120)


class TwinProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    twin_id: uuid.UUID
    communication_style_preset: str
    communication_style_notes: str | None
    basic_profile: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TwinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    profile: TwinProfileOut
    created_at: datetime
    updated_at: datetime
