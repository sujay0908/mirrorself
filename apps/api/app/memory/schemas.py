"""Pydantic schemas for memory + candidate endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryType = Literal["FACT", "PREFERENCE", "EXPERIENCE", "GOAL"]
MemorySourceType = Literal["message", "user_edit", "import"]
CandidateStatus = Literal["pending", "confirmed", "rejected", "expired"]


class MemorySourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: MemorySourceType
    source_message_id: uuid.UUID | None
    source_conversation_id: uuid.UUID | None
    source_metadata: dict[str, Any]
    created_at: datetime


class MemoryEmbeddingOut(BaseModel):
    """Metadata view of an embedding — the vector itself is NOT returned
    through the API by default. Retrieval and inspection endpoints come in
    Sprint 3+.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    embedding_model: str
    embedding_dimensions: int
    created_at: datetime


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    twin_id: uuid.UUID
    type: MemoryType
    content: str
    source: str
    confidence: float
    importance: float
    user_confirmed: bool
    last_confirmed_at: datetime | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    sources: list[MemorySourceOut] = Field(default_factory=list)
    embeddings: list[MemoryEmbeddingOut] = Field(default_factory=list)


class MemoryPatch(BaseModel):
    """Editable fields on a confirmed memory.

    Deliberately does NOT include `user_confirmed`. Confirming a candidate
    is the only path that creates a user-confirmed memory; patching is for
    editing content the user already accepted.
    """

    content: str | None = Field(default=None, min_length=1, max_length=4000)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class MemoryListOut(BaseModel):
    items: list[MemoryOut]


class MemoryCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    twin_id: uuid.UUID
    type: MemoryType
    content: str
    confidence: float
    importance: float
    source_message_id: uuid.UUID | None
    source_conversation_id: uuid.UUID | None
    status: CandidateStatus
    resulting_memory_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MemoryCandidateListOut(BaseModel):
    items: list[MemoryCandidateOut]


class MemoryCandidateConfirmOut(BaseModel):
    candidate: MemoryCandidateOut
    memory: MemoryOut
    # Non-fatal diagnostic: did the embedding attach succeed?
    # The Memory is created regardless.
    embedding_attached: bool
    embedding_error: str | None = None


class MemoryCandidateDraft(BaseModel):
    """Shape returned by the MemoryExtractor and persisted by the service."""

    type: MemoryType
    content: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    importance: float = Field(ge=0.0, le=1.0, default=0.5)
    rationale: str | None = None
