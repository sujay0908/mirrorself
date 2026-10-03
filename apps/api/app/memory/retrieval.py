"""Memory retrieval service — the first consumer of pgvector.

Public surface: ``MemoryRetriever.retrieve(twin, query_text, limit, types)``.
Returns ``RetrievalResult`` with a bounded list of ``RetrievedMemory`` and a
``metadata`` dict suitable for structured logging. Never raises into the
caller — any failure returns an empty result with ``error`` set.

Dialect handling:
- On PostgreSQL, the query uses pgvector's cosine-distance operator (``<=>``)
  to rank candidates server-side, then applies the ranking policy for a
  final transparent ordering.
- On SQLite (tests), the retriever loads candidate rows and computes cosine
  similarity in Python. Produces the SAME ordering so test assertions and
  production behaviour agree.

Guardrails:
- Hard cap `MAX_LIMIT` so callers can never ask for everything.
- Only `user_confirmed=True` memories with a non-NULL `embedding_vector`
  participate in retrieval. Pending / rejected candidates and NULL vectors
  are silently excluded.
- Scoped by ``twin.id`` — cross-twin / cross-user retrieval is impossible
  through this API because the retriever only accepts an in-process
  ``Twin`` ORM instance resolved from the authenticated user upstream.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.interface import EmbeddingProvider, EmbeddingRequest
from app.memory.models import Memory, MemoryEmbedding, MemorySource
from app.memory.ranking import (
    DEFAULT_RANKING_WEIGHTS,
    RankedCandidate,
    RankingInputs,
    RankingWeights,
    rank_candidates,
)
from app.observability.logging import get_logger
from app.twin.models import Twin

logger = get_logger(__name__)

MAX_LIMIT = 24
DEFAULT_LIMIT = 8
MEMORY_TYPES_VALID = {"FACT", "PREFERENCE", "EXPERIENCE", "GOAL"}


@dataclass(slots=True)
class RetrievedMemory:
    memory: Memory
    sources: list[MemorySource]
    similarity: float
    score: float
    ranking_components: dict[str, float]


@dataclass(slots=True)
class RetrievalResult:
    items: list[RetrievedMemory] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _resolve_embedding_model(provider: EmbeddingProvider) -> str:
    for attr in ("_default_model", "default_model", "model"):
        value = getattr(provider, attr, None)
        if value:
            return str(value)
    return provider.provider_name + "-default"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    denom = math.sqrt(na) * math.sqrt(nb)
    if denom == 0.0:
        return 0.0
    return dot / denom


class MemoryRetriever:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        *,
        weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
        max_limit: int = MAX_LIMIT,
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._weights = weights
        self._max_limit = max_limit

    async def retrieve(
        self,
        twin: Twin,
        query_text: str,
        *,
        limit: int = DEFAULT_LIMIT,
        types: list[str] | None = None,
    ) -> RetrievalResult:
        """Entry point. NEVER raises."""
        started = time.perf_counter()
        safe_limit = max(1, min(limit, self._max_limit))
        type_filter: set[str] | None = None
        if types is not None:
            type_filter = {t for t in types if t in MEMORY_TYPES_VALID}
            if not type_filter:
                return RetrievalResult(
                    metadata={
                        "duration_ms": 0,
                        "memories_considered": 0,
                        "memories_returned": 0,
                        "limit": safe_limit,
                        "reason": "no_valid_type_filter",
                    }
                )

        try:
            embed_resp = await self._embedding_provider.embed(
                EmbeddingRequest(
                    texts=[query_text],
                    model=_resolve_embedding_model(self._embedding_provider),
                )
            )
        except Exception as exc:
            return RetrievalResult(
                error=f"embedding_provider_error:{type(exc).__name__}",
                metadata={
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "memories_considered": 0,
                    "memories_returned": 0,
                    "limit": safe_limit,
                    "twin_id": str(twin.id),
                },
            )

        if not embed_resp.embeddings:
            return RetrievalResult(
                error="empty_embedding_response",
                metadata={
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "memories_considered": 0,
                    "memories_returned": 0,
                    "limit": safe_limit,
                    "twin_id": str(twin.id),
                },
            )

        query_vec = embed_resp.embeddings[0]

        try:
            raw_candidates = await self._gather_candidates(
                twin=twin,
                query_vec=query_vec,
                type_filter=type_filter,
                fetch_limit=self._max_limit * 2,
            )
        except Exception as exc:
            return RetrievalResult(
                error=f"query_error:{type(exc).__name__}",
                metadata={
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "memories_considered": 0,
                    "memories_returned": 0,
                    "limit": safe_limit,
                    "twin_id": str(twin.id),
                },
            )

        inputs = [
            RankingInputs(
                memory_id=str(mem.id),
                similarity=similarity,
                importance=mem.importance,
                confidence=mem.confidence,
                user_confirmed=mem.user_confirmed,
                created_at=mem.created_at,
                last_confirmed_at=mem.last_confirmed_at,
            )
            for mem, similarity in raw_candidates
        ]
        ranked_lookup: dict[str, RankedCandidate] = {
            rc.memory_id: rc for rc in rank_candidates(inputs, weights=self._weights)
        }

        memory_by_id = {str(m.id): (m, sim) for m, sim in raw_candidates}
        ranked_items: list[RetrievedMemory] = []
        for memory_id, rc in sorted(
            ranked_lookup.items(), key=lambda kv: (-kv[1].score, kv[0])
        ):
            mem, sim = memory_by_id[memory_id]
            ranked_items.append(
                RetrievedMemory(
                    memory=mem,
                    sources=list(mem.sources),
                    similarity=sim,
                    score=rc.score,
                    ranking_components=rc.components,
                )
            )
            if len(ranked_items) >= safe_limit:
                break

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "memory.retrieval.ok",
            duration_ms=duration_ms,
            memories_considered=len(raw_candidates),
            memories_returned=len(ranked_items),
            limit=safe_limit,
            types=sorted(type_filter) if type_filter else None,
            twin_id=str(twin.id),
            provider=self._embedding_provider.provider_name,
        )
        return RetrievalResult(
            items=ranked_items,
            metadata={
                "duration_ms": duration_ms,
                "memories_considered": len(raw_candidates),
                "memories_returned": len(ranked_items),
                "limit": safe_limit,
                "twin_id": str(twin.id),
                "provider": self._embedding_provider.provider_name,
            },
        )

    async def _gather_candidates(
        self,
        *,
        twin: Twin,
        query_vec: list[float],
        type_filter: set[str] | None,
        fetch_limit: int,
    ) -> list[tuple[Memory, float]]:
        """Fetch candidate (Memory, similarity) pairs scoped to this twin."""
        dialect = self._session.bind.dialect.name if self._session.bind else "unknown"

        if dialect == "postgresql":
            return await self._pg_candidates(
                twin=twin,
                query_vec=query_vec,
                type_filter=type_filter,
                fetch_limit=fetch_limit,
            )
        return await self._portable_candidates(
            twin=twin,
            query_vec=query_vec,
            type_filter=type_filter,
            fetch_limit=fetch_limit,
        )

    async def _pg_candidates(
        self,
        *,
        twin: Twin,
        query_vec: list[float],
        type_filter: set[str] | None,
        fetch_limit: int,
    ) -> list[tuple[Memory, float]]:
        """Postgres path — uses pgvector cosine distance for ANN-friendly
        ordering, then returns (memory, cosine_similarity) pairs for the
        ranking policy to re-score transparently.
        """
        from sqlalchemy.orm import selectinload

        stmt = (
            select(
                Memory,
                MemoryEmbedding.embedding_vector.cosine_distance(query_vec).label("dist"),
            )
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .where(
                Memory.twin_id == twin.id,
                Memory.user_confirmed.is_(True),
                MemoryEmbedding.embedding_vector.is_not(None),
            )
            .order_by("dist")
            .limit(fetch_limit)
            .options(selectinload(Memory.sources))
        )
        if type_filter is not None:
            stmt = stmt.where(Memory.type.in_(type_filter))
        rows = (await self._session.execute(stmt)).all()
        return [(mem, 1.0 - float(dist)) for mem, dist in rows]

    async def _portable_candidates(
        self,
        *,
        twin: Twin,
        query_vec: list[float],
        type_filter: set[str] | None,
        fetch_limit: int,
    ) -> list[tuple[Memory, float]]:
        """Dialect-portable path. Walks confirmed memories with a non-NULL
        embedding_vector, computes cosine in Python, and keeps top ``fetch_limit``.

        Used in the SQLite test environment. Linear in confirmed memories.
        """
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Memory, MemoryEmbedding)
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .where(
                Memory.twin_id == twin.id,
                Memory.user_confirmed.is_(True),
                MemoryEmbedding.embedding_vector.is_not(None),
            )
            .options(selectinload(Memory.sources))
        )
        if type_filter is not None:
            stmt = stmt.where(Memory.type.in_(type_filter))
        rows = (await self._session.execute(stmt)).all()
        pairs: list[tuple[Memory, float]] = []
        for mem, emb in rows:
            if emb.embedding_vector is None:
                continue
            sim = _cosine(query_vec, list(emb.embedding_vector))
            pairs.append((mem, sim))
        pairs.sort(key=lambda t: -t[1])
        return pairs[:fetch_limit]
