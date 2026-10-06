"""Memory domain service.

Owns:
- CRUD on confirmed memories (list, get, patch, delete).
- Candidate lifecycle (list, confirm, reject).
- Best-effort embedding attach on confirmation.

Rules:
- No path writes to `TwinProfile`. The module does not import it.
- Every read/write scopes by `twin.id` (which is already filtered by
  `twin.user_id == auth.user_id` upstream).
- Patch cannot flip `user_confirmed` — only candidate confirmation can.
- Hard delete removes a memory and cascades sources + embeddings. The
  originating candidate (if any) is preserved with `status='confirmed'`
  for audit.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.conversation.models import Message
from app.llm.interface import EmbeddingProvider, EmbeddingRequest
from app.memory.errors import (
    MemoryCandidateAlreadyResolvedError,
    MemoryCandidateNotFoundError,
    MemoryNotFoundError,
)
from app.memory.models import (
    SEMANTIC_EMBEDDING_DIM,
    Memory,
    MemoryCandidate,
    MemoryEmbedding,
    MemorySource,
)
from app.memory.schemas import (
    PROVENANCE_SNIPPET_MAX_CHARS,
    MemoryCandidateDraft,
    MemoryPatch,
)
from app.observability.logging import get_logger
from app.twin.models import Twin

logger = get_logger(__name__)


class MemoryService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider

    # ------------- Memory CRUD -------------

    async def list_for_twin(
        self,
        twin: Twin,
        *,
        type: str | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        stmt = (
            select(Memory)
            .where(Memory.twin_id == twin.id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .options(
                selectinload(Memory.sources),
                selectinload(Memory.embeddings),
            )
        )
        if type is not None:
            stmt = stmt.where(Memory.type == type)
        return list((await self._session.execute(stmt)).scalars())

    async def get(self, twin: Twin, memory_id: uuid.UUID) -> Memory:
        stmt = (
            select(Memory)
            .where(Memory.id == memory_id, Memory.twin_id == twin.id)
            .options(
                selectinload(Memory.sources),
                selectinload(Memory.embeddings),
            )
        )
        memory = (await self._session.execute(stmt)).scalar_one_or_none()
        if memory is None:
            raise MemoryNotFoundError(
                "Memory not found or not yours.",
                details={"memory_id": str(memory_id)},
            )
        return memory

    async def patch(self, twin: Twin, memory_id: uuid.UUID, patch: MemoryPatch) -> Memory:
        """Edit a memory the user already accepted.

        Deliberately rejects any field named `user_confirmed`. The only path
        to a user-confirmed memory is `confirm_candidate`.
        """
        memory = await self.get(twin, memory_id)
        if patch.content is not None:
            memory.content = patch.content
        if patch.importance is not None:
            memory.importance = patch.importance
        if patch.metadata is not None:
            memory.metadata_json = patch.metadata
        await self._session.commit()
        await self._session.refresh(memory)
        logger.info("memory.updated", memory_id=str(memory.id))
        return memory

    async def supersede(
        self,
        twin: Twin,
        memory_id: uuid.UUID,
        by_memory_id: uuid.UUID,
    ) -> Memory:
        """Mark `memory_id` as superseded by `by_memory_id` (Sprint 7).

        Non-destructive: both rows stay intact. Retrieval filters by
        `superseded_by_memory_id IS NULL` so only the canonical row
        participates in future prompts; the memory list endpoint still
        returns the superseded row so the user can inspect or
        un-supersede it.

        Both IDs must belong to the authenticated user's twin. A
        cross-twin supersede attempt raises `MemoryNotFoundError`
        (via `self.get`) rather than leaking existence.
        """
        if memory_id == by_memory_id:
            raise MemoryNotFoundError(
                "A memory cannot supersede itself.",
                details={"memory_id": str(memory_id)},
            )
        superseded = await self.get(twin, memory_id)
        canonical = await self.get(twin, by_memory_id)
        superseded.superseded_by_memory_id = canonical.id
        await self._session.commit()
        await self._session.refresh(superseded)
        logger.info(
            "memory.superseded",
            memory_id=str(superseded.id),
            canonical_memory_id=str(canonical.id),
            twin_id=str(twin.id),
        )
        return superseded

    async def unsupersede(self, twin: Twin, memory_id: uuid.UUID) -> Memory:
        """Clear the supersession pointer on a previously-superseded memory.

        Reversibility is a product promise — a confirmed `memory_dedup`
        reflection is not a one-way trip. If the memory was not
        superseded in the first place this is a no-op.
        """
        memory = await self.get(twin, memory_id)
        memory.superseded_by_memory_id = None
        await self._session.commit()
        await self._session.refresh(memory)
        logger.info(
            "memory.unsuperseded",
            memory_id=str(memory.id),
            twin_id=str(twin.id),
        )
        return memory

    async def delete(self, twin: Twin, memory_id: uuid.UUID) -> None:
        memory = await self.get(twin, memory_id)
        await self._session.delete(memory)
        await self._session.commit()
        logger.info("memory.deleted", memory_id=str(memory_id))

    async def get_provenance(
        self, twin: Twin, memory_id: uuid.UUID
    ) -> tuple[Memory, list[tuple[MemorySource, str | None, bool]]]:
        """Return the memory and its sources with bounded source snippets.

        For each `MemorySource` on the memory, if `source_message_id` is set
        and the message still exists AND the message belongs to a conversation
        under this twin (defence in depth — the twin-ownership check at the
        memory level is enough but we don't want to leak another user's
        message content if a bug ever broke that), its content is truncated
        to ``PROVENANCE_SNIPPET_MAX_CHARS`` characters and returned alongside
        the source. Otherwise the snippet is `None`.

        Returns `[(source, snippet, truncated), ...]` for callers to format.
        """
        memory = await self.get(twin, memory_id)
        out: list[tuple[MemorySource, str | None, bool]] = []
        for source in memory.sources:
            snippet, truncated = await self._source_snippet(twin, source)
            out.append((source, snippet, truncated))
        return memory, out

    async def _source_snippet(self, twin: Twin, source: MemorySource) -> tuple[str | None, bool]:
        if source.source_message_id is None:
            return None, False
        # Look up the message AND join to its conversation so we only read
        # content that actually belongs to this user's twin. If the message
        # was deleted (FK was set to NULL) or lives under another twin, the
        # snippet is None.
        from app.conversation.models import Conversation  # local import avoids cycle

        stmt = (
            select(Message.content)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == source.source_message_id,
                Conversation.twin_id == twin.id,
            )
        )
        content = (await self._session.execute(stmt)).scalar_one_or_none()
        if content is None:
            return None, False
        if len(content) > PROVENANCE_SNIPPET_MAX_CHARS:
            return content[:PROVENANCE_SNIPPET_MAX_CHARS] + "…", True
        return content, False

    # ------------- Candidate lifecycle -------------

    async def create_candidates(
        self,
        twin: Twin,
        drafts: list[MemoryCandidateDraft],
        *,
        source_conversation_id: uuid.UUID | None = None,
        source_message_id: uuid.UUID | None = None,
    ) -> list[MemoryCandidate]:
        if not drafts:
            return []
        created: list[MemoryCandidate] = []
        for draft in drafts:
            row = MemoryCandidate(
                user_id=twin.user_id,
                twin_id=twin.id,
                type=draft.type,
                content=draft.content,
                confidence=draft.confidence,
                importance=draft.importance,
                source_conversation_id=source_conversation_id,
                source_message_id=source_message_id,
                rationale=draft.rationale,
                status="pending",
            )
            self._session.add(row)
            created.append(row)
        await self._session.flush()
        await self._session.commit()
        for row in created:
            await self._session.refresh(row)
        logger.info(
            "memory.candidates.persisted",
            twin_id=str(twin.id),
            count=len(created),
        )
        return created

    async def list_candidates(
        self,
        twin: Twin,
        *,
        status: str | None = "pending",
    ) -> list[MemoryCandidate]:
        stmt = (
            select(MemoryCandidate)
            .where(MemoryCandidate.twin_id == twin.id)
            .order_by(MemoryCandidate.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(MemoryCandidate.status == status)
        return list((await self._session.execute(stmt)).scalars())

    async def get_candidate(self, twin: Twin, candidate_id: uuid.UUID) -> MemoryCandidate:
        stmt = select(MemoryCandidate).where(
            MemoryCandidate.id == candidate_id,
            MemoryCandidate.twin_id == twin.id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise MemoryCandidateNotFoundError(
                "Candidate not found or not yours.",
                details={"candidate_id": str(candidate_id)},
            )
        return row

    async def confirm_candidate(
        self, twin: Twin, candidate_id: uuid.UUID
    ) -> tuple[MemoryCandidate, Memory, bool, str | None]:
        """Confirm a pending candidate.

        Guarantees (per Sprint 2 modification 1):
        - Memory + MemorySource are created in one DB transaction, committed
          BEFORE any embedding attempt. If the embedding call fails or the
          embedding provider is misconfigured, the memory still exists.
        - Returns `(candidate, memory, embedding_attached, error_message)`.
        """
        candidate = await self.get_candidate(twin, candidate_id)
        if candidate.status != "pending":
            raise MemoryCandidateAlreadyResolvedError(
                f"Candidate is already {candidate.status!r}.",
                details={
                    "candidate_id": str(candidate.id),
                    "status": candidate.status,
                },
            )

        now = datetime.now(tz=UTC)
        memory = Memory(
            user_id=twin.user_id,
            twin_id=twin.id,
            type=candidate.type,
            content=candidate.content,
            source="candidate_confirmation",
            confidence=candidate.confidence,
            importance=candidate.importance,
            user_confirmed=True,
            last_confirmed_at=now,
            metadata_json={"candidate_id": str(candidate.id)},
        )
        self._session.add(memory)
        await self._session.flush()  # populate memory.id

        source = MemorySource(
            memory_id=memory.id,
            source_type="message" if candidate.source_message_id else "user_edit",
            source_message_id=candidate.source_message_id,
            source_conversation_id=candidate.source_conversation_id,
            source_metadata={"candidate_id": str(candidate.id)},
        )
        self._session.add(source)

        candidate.status = "confirmed"
        candidate.resulting_memory_id = memory.id

        # COMMIT NOW — the memory and its provenance are permanent at this
        # point. The embedding attach below runs on a separate transaction
        # and never affects this commit's outcome.
        await self._session.commit()
        await self._session.refresh(memory, attribute_names=["sources", "embeddings"])
        await self._session.refresh(candidate)

        logger.info(
            "memory.candidate.confirmed",
            candidate_id=str(candidate.id),
            memory_id=str(memory.id),
            twin_id=str(twin.id),
        )

        embedding_attached, embedding_error = await self._best_effort_embed(memory)
        return candidate, memory, embedding_attached, embedding_error

    async def reject_candidate(self, twin: Twin, candidate_id: uuid.UUID) -> MemoryCandidate:
        candidate = await self.get_candidate(twin, candidate_id)
        if candidate.status != "pending":
            raise MemoryCandidateAlreadyResolvedError(
                f"Candidate is already {candidate.status!r}.",
                details={
                    "candidate_id": str(candidate.id),
                    "status": candidate.status,
                },
            )
        candidate.status = "rejected"
        await self._session.commit()
        await self._session.refresh(candidate)
        logger.info(
            "memory.candidate.rejected",
            candidate_id=str(candidate.id),
            twin_id=str(twin.id),
        )
        return candidate

    # ------------- Internal: embeddings -------------

    async def _best_effort_embed(self, memory: Memory) -> tuple[bool, str | None]:
        """Attach an embedding row — on any failure, log and return False.

        NEVER raises. Two failure classes handled independently so a provider
        error does not touch the already-committed Memory:
        (1) provider.embed() itself raises → no DB changes attempted.
        (2) commit of the new embedding row raises → rollback (which affects
            only the row we just added, since the Memory was committed above).
        """
        if self._embedding_provider is None:
            logger.info(
                "memory.embedding.skipped",
                reason="no_embedding_provider",
                memory_id=str(memory.id),
            )
            return False, "no_embedding_provider"
        try:
            resp = await self._embedding_provider.embed(
                EmbeddingRequest(
                    texts=[memory.content],
                    model=_resolve_model_for_provider(self._embedding_provider),
                )
            )
        except Exception as exc:
            logger.warning(
                "memory.embedding.provider_failed",
                memory_id=str(memory.id),
                error=type(exc).__name__,
            )
            return False, type(exc).__name__

        if not resp.embeddings:
            return False, "empty_embedding_response"

        raw_vector = resp.embeddings[0]
        # Populate the Sprint 3 pgvector column ONLY when the provider's
        # vector matches the pinned retrieval dimension. Other-dimension
        # providers still land in the legacy JSON `vector` column so no
        # memory is lost, but they will not appear in semantic retrieval
        # until a backfill job re-embeds them with the configured model.
        semantic_vector: list[float] | None = (
            list(raw_vector) if resp.dimensions == SEMANTIC_EMBEDDING_DIM else None
        )
        emb = MemoryEmbedding(
            memory_id=memory.id,
            embedding_model=resp.model,
            embedding_dimensions=resp.dimensions,
            vector=raw_vector,
            embedding_vector=semantic_vector,
        )
        self._session.add(emb)
        try:
            await self._session.commit()
        except Exception as exc:  # pragma: no cover
            with contextlib.suppress(Exception):
                await self._session.rollback()
            logger.warning(
                "memory.embedding.commit_failed",
                memory_id=str(memory.id),
                error=type(exc).__name__,
            )
            return False, type(exc).__name__

        await self._session.refresh(memory, attribute_names=["embeddings"])
        logger.info(
            "memory.embedding.attached",
            memory_id=str(memory.id),
            model=resp.model,
            dimensions=resp.dimensions,
            semantic_vector_present=semantic_vector is not None,
        )
        return True, None


def _resolve_model_for_provider(provider: EmbeddingProvider) -> str:
    """Each provider instance may carry its own default model.

    Falls back to a conventional name if nothing is attached.
    """
    for attr in ("_default_model", "default_model", "model"):
        value = getattr(provider, attr, None)
        if value:
            return str(value)
    return provider.provider_name + "-default"
