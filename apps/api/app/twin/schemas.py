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


# ---------------------------------------------------------------
# Sprint 9: Self-Portrait response schemas.
#
# The portrait is a DETERMINISTIC composition of already-authorized
# user-owned data. No LLM. No narrative generation. The schemas below
# are intentionally a strict subset of the service-facing types — e.g.
# a bounded memory snippet rather than the full MemoryOut graph —
# because the portrait is a trust surface.
# ---------------------------------------------------------------


EvolutionLead = Literal["learned", "acknowledged"]


class PortraitProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str
    style_preset: str
    style_notes: str | None
    basic_profile: dict[str, Any]


class PortraitMemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    importance: float
    snippet: str


class PortraitMemorySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_count: int
    counts_by_type: dict[str, int]
    top_memories: list[PortraitMemoryOut] = Field(default_factory=list)


class PortraitGoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    priority: int
    target_date: datetime | None


class PortraitEvolutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    summary: str
    created_at: datetime
    lead: EvolutionLead


class TwinPortraitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile: PortraitProfileOut
    memory_summary: PortraitMemorySummaryOut
    active_goals: list[PortraitGoalOut] = Field(default_factory=list)
    recent_evolution: list[PortraitEvolutionOut] = Field(default_factory=list)
