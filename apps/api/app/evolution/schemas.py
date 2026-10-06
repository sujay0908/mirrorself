"""Pydantic schemas for the Twin evolution surface (Sprint 8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvolutionEventType = Literal[
    "memory_learned",
    "memory_consolidated",
    "goal_updated",
    "profile_confirmed",
    "insight_acknowledged",
]


class EvolutionEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    twin_id: uuid.UUID
    event_type: EvolutionEventType
    reflection_id: uuid.UUID | None = None
    memory_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    profile_field: str | None = None
    summary: str
    created_at: datetime


class EvolutionListOut(BaseModel):
    items: list[EvolutionEventOut] = Field(default_factory=list)
