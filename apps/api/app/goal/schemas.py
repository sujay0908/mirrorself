"""Pydantic request/response schemas for the Goal endpoints.

Validation rules:

- `title` is required, 1..200 chars.
- `description` is optional, up to 4000 chars.
- `priority` is 1..5 (1 = highest).
- `status` on an incoming update is one of the four GOAL_STATUSES. The
  LEGAL transition is enforced by `GoalService`, not here.
- `target_date` is optional and must be timezone-aware in payloads; the
  service will attach UTC to naive values defensively.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GoalStatus = Literal["active", "achieved", "abandoned", "paused"]
GoalEventType = Literal["created", "updated", "status_changed"]


class GoalCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    target_date: datetime | None = None
    priority: int = Field(default=3, ge=1, le=5)


class GoalUpdateIn(BaseModel):
    """PATCH body. All fields optional; missing = unchanged.

    Status transitions go through this same endpoint; the service rejects
    illegal transitions. See GoalService._assert_legal_transition.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    target_date: datetime | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: GoalStatus | None = None
    status_note: str | None = Field(default=None, max_length=2000)


class GoalEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    goal_id: uuid.UUID
    event_type: GoalEventType
    from_status: GoalStatus | None
    to_status: GoalStatus | None
    note: str | None
    created_at: datetime


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    twin_id: uuid.UUID
    title: str
    description: str | None
    target_date: datetime | None
    priority: int
    status: GoalStatus
    status_changed_at: datetime
    created_at: datetime
    updated_at: datetime


class GoalListOut(BaseModel):
    items: list[GoalOut]


class GoalEventsOut(BaseModel):
    items: list[GoalEventOut]
