"""Memory retrieval tests.

Covers:
- confirmation filtering (pending/rejected memories skipped)
- NULL embedding_vector skipped
- type filtering
- cross-twin isolation (hard Sprint 3 invariant)
- cross-user isolation
- limit cap enforcement
- provenance preserved on returned memories
"""

from __future__ import annotations

import pytest

from app.api.deps import (
    get_current_user,
    sessionmaker_dep,
)
from app.llm.providers.mock_embedding import MockEmbeddingProvider
from app.memory.models import SEMANTIC_EMBEDDING_DIM
from app.memory.retrieval import MAX_LIMIT, MemoryRetriever
from app.memory.schemas import MemoryCandidateDraft
from app.memory.service import MemoryService
from app.twin.service import TwinService

# ------------- helpers -------------


async def _twin_for(app, holder, user):
    """Resolve the Twin for the given user via the test fixtures."""
    holder.user = user
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        return twin


async def _create_memory(
    app,
    holder,
    user,
    *,
    content: str,
    mem_type: str = "FACT",
    confirmed: bool = True,
):
    """Create a candidate for `user`, confirm it (so a Memory lands), and
    return the resulting memory dict. Uses the actual service so the
    semantic vector column is populated the same way production does.
    """
    holder.user = user
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(
                dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"
            ),
        )
        [candidate] = await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type=mem_type,
                    content=content,
                    confidence=0.9,
                    importance=0.8,
                )
            ],
        )
    if not confirmed:
        return candidate
    # Confirm via HTTP so the full code path exercises.
    resp = await (await _client_for(app)).post(f"/v1/memory-candidates/{candidate.id}/confirm")
    assert resp.status_code == 201, resp.text
    return resp.json()["memory"]


async def _client_for(app):
    """Return the AsyncClient attached to the running test app."""
    # Fixtures hand us the client directly in the test functions; this
    # helper is here only for the service-level seed path above.
    raise NotImplementedError("use the `client` fixture directly in tests")


# ------------- tests via the real fixture `client` -------------


@pytest.mark.asyncio
async def test_confirmed_memory_is_retrieved(client, session_factory) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    # Create + confirm one memory.
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    user_fn = app.dependency_overrides[get_current_user]
    user = (await user_fn()) if callable(user_fn) else user_fn
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(
                dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"
            ),
        )
        [cand] = await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content="I live in Bengaluru.",
                    confidence=0.9,
                    importance=0.8,
                )
            ],
        )
    resp = await client.post(f"/v1/memory-candidates/{cand.id}/confirm")
    assert resp.status_code == 201

    # Retrieve directly via the service (bypassing HTTP) using the SAME
    # embedding provider the test seeded with — gives deterministic sim.
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        retriever = MemoryRetriever(
            session,
            MockEmbeddingProvider(dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"),
        )
        result = await retriever.retrieve(twin, "I live in Bengaluru.")
    assert result.ok
    assert len(result.items) == 1
    assert result.items[0].memory.content == "I live in Bengaluru."
    assert result.items[0].sources, "provenance (sources) must survive retrieval"


@pytest.mark.asyncio
async def test_pending_memory_candidate_is_not_retrieved(client) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    user_fn = app.dependency_overrides[get_current_user]
    user = (await user_fn()) if callable(user_fn) else user_fn
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(
                dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"
            ),
        )
        await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content="Candidate not yet confirmed.",
                    confidence=0.9,
                    importance=0.8,
                )
            ],
        )
        retriever = MemoryRetriever(
            session,
            MockEmbeddingProvider(dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"),
        )
        result = await retriever.retrieve(twin, "Candidate not yet confirmed.")
    assert result.ok
    assert result.items == []


@pytest.mark.asyncio
async def test_rejected_memory_is_not_retrieved(client) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    user_fn = app.dependency_overrides[get_current_user]
    user = (await user_fn()) if callable(user_fn) else user_fn
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(
                dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"
            ),
        )
        [cand] = await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content="Will be rejected.",
                    confidence=0.9,
                    importance=0.8,
                )
            ],
        )
    rej = await client.post(f"/v1/memory-candidates/{cand.id}/reject")
    assert rej.status_code == 200

    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        retriever = MemoryRetriever(
            session,
            MockEmbeddingProvider(dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"),
        )
        result = await retriever.retrieve(twin, "anything")
    assert result.items == []


@pytest.mark.asyncio
async def test_null_embedding_memory_is_skipped(client) -> None:
    """A memory that was confirmed WITHOUT a semantic vector (e.g. the
    embedding provider was offline) must still exist as a memory but must
    be skipped by semantic retrieval.
    """
    await client.post("/v1/twin", json={"name": "Aurora"})
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    user_fn = app.dependency_overrides[get_current_user]
    user = (await user_fn()) if callable(user_fn) else user_fn
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(
                dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"
            ),
        )
        [cand] = await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content="Null-vector memory.",
                    confidence=0.9,
                    importance=0.8,
                )
            ],
        )
    import uuid as _uuid

    confirmed = await client.post(f"/v1/memory-candidates/{cand.id}/confirm")
    memory_id_str = confirmed.json()["memory"]["id"]
    memory_id = _uuid.UUID(memory_id_str)
    # Null the semantic vector manually (simulating a legacy Sprint 2 row
    # or a historical provider failure).
    from sqlalchemy import update

    from app.memory.models import MemoryEmbedding

    async with sessionmaker() as session:
        await session.execute(
            update(MemoryEmbedding)
            .where(MemoryEmbedding.memory_id == memory_id)
            .values(embedding_vector=None)
        )
        await session.commit()

    # Memory itself still visible via listing.
    listed = await client.get("/v1/memories")
    assert any(m["id"] == memory_id_str for m in listed.json()["items"])

    # But retrieval skips it.
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        retriever = MemoryRetriever(
            session,
            MockEmbeddingProvider(dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"),
        )
        result = await retriever.retrieve(twin, "Null-vector memory.")
    assert result.items == []


@pytest.mark.asyncio
async def test_type_filter_excludes_others(client) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    user_fn = app.dependency_overrides[get_current_user]
    user = (await user_fn()) if callable(user_fn) else user_fn
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(
                dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"
            ),
        )
        candidates = await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content="A fact.",
                    confidence=0.9,
                    importance=0.5,
                ),
                MemoryCandidateDraft(
                    type="PREFERENCE",
                    content="A preference.",
                    confidence=0.9,
                    importance=0.5,
                ),
            ],
        )
    for c in candidates:
        await client.post(f"/v1/memory-candidates/{c.id}/confirm")

    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        retriever = MemoryRetriever(
            session,
            MockEmbeddingProvider(dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"),
        )
        only_facts = await retriever.retrieve(twin, "x", types=["FACT"])
        all_types = await retriever.retrieve(twin, "x")
    assert {r.memory.type for r in only_facts.items} == {"FACT"}
    assert {r.memory.type for r in all_types.items} == {"FACT", "PREFERENCE"}


@pytest.mark.asyncio
async def test_cross_user_and_cross_twin_isolation(
    client, as_user, user_a, user_b, session_factory
) -> None:
    # User A: twin + confirmed memory.
    as_user(user_a)
    await client.post("/v1/twin", json={"name": "A's twin"})
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    async with sessionmaker() as session:
        twin_a = await TwinService(session).require_by_user(user_a.user_id)
        service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(
                dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"
            ),
        )
        [cand] = await service.create_candidates(
            twin_a,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content="A's private fact.",
                    confidence=0.9,
                    importance=0.5,
                )
            ],
        )
    await client.post(f"/v1/memory-candidates/{cand.id}/confirm")

    # User B: separate twin.
    as_user(user_b)
    await client.post("/v1/twin", json={"name": "B's twin"})
    async with sessionmaker() as session:
        twin_b = await TwinService(session).require_by_user(user_b.user_id)
        retriever = MemoryRetriever(
            session,
            MockEmbeddingProvider(dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"),
        )
        result = await retriever.retrieve(twin_b, "A's private fact.")
    assert result.ok
    assert result.items == [], "B must never retrieve A's memories"


@pytest.mark.asyncio
async def test_limit_is_capped(client) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    user_fn = app.dependency_overrides[get_current_user]
    user = (await user_fn()) if callable(user_fn) else user_fn

    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(
                dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"
            ),
        )
        candidates = await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content=f"fact {i}",
                    confidence=0.9,
                    importance=0.5,
                )
                for i in range(30)
            ],
        )
    for c in candidates:
        await client.post(f"/v1/memory-candidates/{c.id}/confirm")

    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        retriever = MemoryRetriever(
            session,
            MockEmbeddingProvider(dimensions=SEMANTIC_EMBEDDING_DIM, model="mock-embed-1"),
        )
        # Ask for way more than MAX_LIMIT; retriever must cap us.
        result = await retriever.retrieve(twin, "anything", limit=1000)
    assert len(result.items) <= MAX_LIMIT
