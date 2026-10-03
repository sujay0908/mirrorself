"""SQLAlchemy models for the memory domain.

Four tables:

- `memories` — the Twin's accumulated, user-controlled knowledge.
- `memory_sources` — provenance; where each memory came from.
- `memory_embeddings` — vector representations keyed per model (nullable
  for a memory; embedding is best-effort and never gates confirmation).
- `memory_candidates` — proposed memories pending user confirmation.

Rules enforced here (and reinforced by tests):

- `Memory` has no path to `TwinProfile`. The service layer does not import
  `TwinProfile`. Profile mutation remains gated to `TwinService.update`.
- Embedding dimensions are stored per row — never a domain constant.
- Hard delete on `memories` cascades to its sources and embeddings; the
  original `MemoryCandidate` is kept with `status='confirmed'` for audit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.db.types import VectorColumn

# Sprint 3 pins semantic retrieval to a single dimension so pgvector can
# use typed `vector(N)` indexes. Changing this requires a new migration.
SEMANTIC_EMBEDDING_DIM: int = 1536

if TYPE_CHECKING:
    pass


# MVP memory type values (also enforced by DB CHECK).
MEMORY_TYPES: tuple[str, ...] = ("FACT", "PREFERENCE", "EXPERIENCE", "GOAL")
MEMORY_SOURCE_TYPES: tuple[str, ...] = ("message", "user_edit", "import")
CANDIDATE_STATUSES: tuple[str, ...] = ("pending", "confirmed", "rejected", "expired")


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Memory(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(
            "type IN ('FACT','PREFERENCE','EXPERIENCE','GOAL')",
            name="memories_type_check",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="memories_confidence_check",
        ),
        CheckConstraint(
            "importance >= 0 AND importance <= 1",
            name="memories_importance_check",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    twin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("twins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    user_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    sources: Mapped[list[MemorySource]] = relationship(
        back_populates="memory",
        cascade="all, delete-orphan",
    )
    embeddings: Mapped[list[MemoryEmbedding]] = relationship(
        back_populates="memory",
        cascade="all, delete-orphan",
    )


class MemorySource(Base, UUIDPKMixin):
    __tablename__ = "memory_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('message','user_edit','import')",
            name="memory_sources_type_check",
        ),
    )

    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Both FKs are nullable so a message-sourced memory survives message
    # deletion with provenance left as "message that no longer exists".
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    memory: Mapped[Memory] = relationship(back_populates="sources")


class MemoryEmbedding(Base, UUIDPKMixin):
    __tablename__ = "memory_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "memory_id", "embedding_model",
            name="uq_memory_embedding_model",
        ),
        CheckConstraint(
            "embedding_dimensions > 0",
            name="memory_embeddings_dims_check",
        ),
    )

    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    # Legacy Sprint 2 JSON vector column. Kept for one release so Sprint 2
    # rows remain readable while retrieval migrates to the typed column
    # below. A later migration will drop this column.
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    # Sprint 3 semantic column. Nullable: rows without a semantic vector
    # (legacy Sprint 2 rows, provider failures) are retrievable AS MEMORIES
    # via listing endpoints but are SKIPPED by semantic retrieval. A future
    # backfill job regenerates missing vectors against the current provider.
    embedding_vector: Mapped[list[float] | None] = mapped_column(
        VectorColumn(SEMANTIC_EMBEDDING_DIM), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    memory: Mapped[Memory] = relationship(back_populates="embeddings")


class MemoryCandidate(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "memory_candidates"
    __table_args__ = (
        CheckConstraint(
            "type IN ('FACT','PREFERENCE','EXPERIENCE','GOAL')",
            name="memory_candidates_type_check",
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','rejected','expired')",
            name="memory_candidates_status_check",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="memory_candidates_confidence_check",
        ),
        CheckConstraint(
            "importance >= 0 AND importance <= 1",
            name="memory_candidates_importance_check",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    twin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("twins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    resulting_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memories.id", ondelete="SET NULL"),
        nullable=True,
    )
