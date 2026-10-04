"""Memory candidate lifecycle: confirm, reject, ownership, embedding
best-effort behaviour.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.deps import (
    get_current_user,
    get_embedding_provider,
    sessionmaker_dep,
)
from app.memory.models import Memory, MemoryEmbedding, MemorySource
from app.memory.schemas import MemoryCandidateDraft
from app.memory.service import MemoryService
from app.twin.service import TwinService
from tests._helpers import FailingEmbeddingProvider


async def _seed_candidate(
    client,
    content: str = "I prefer concise replies in the morning.",
    type_: str = "PREFERENCE",
    confidence: float = 0.9,
    importance: float = 0.8,
) -> dict:
    """Create a Twin and seed one pending candidate via the service.

    Returns the Pydantic-serialised candidate as returned by GET.
    """
    await client.post("/v1/twin", json={"name": "Aurora"})
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user = app.dependency_overrides[get_current_user]
    user = (await user()) if callable(user) else user
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    async with sessionmaker() as session:
        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(session, embedding_provider=None)
        [cand] = await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type=type_,
                    content=content,
                    confidence=confidence,
                    importance=importance,
                    rationale="unit test seed",
                )
            ],
        )
        return {"id": str(cand.id), "status": cand.status, "content": cand.content}


@pytest.mark.asyncio
async def test_list_candidates_defaults_to_pending(client) -> None:
    await _seed_candidate(client)
    resp = await client.get("/v1/memory-candidates")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_confirm_candidate_creates_memory_and_source(client, session_factory) -> None:
    cand = await _seed_candidate(client, content="I live in Bengaluru.")

    resp = await client.post(f"/v1/memory-candidates/{cand['id']}/confirm")
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["candidate"]["status"] == "confirmed"
    assert body["memory"]["user_confirmed"] is True
    assert body["memory"]["content"] == "I live in Bengaluru."
    assert body["memory"]["source"] == "candidate_confirmation"
    assert body["embedding_attached"] is True
    assert body["embedding_error"] is None

    async with session_factory() as s:
        sources = (await s.execute(select(MemorySource))).scalars().all()
        assert len(sources) == 1
        assert str(sources[0].memory_id) == body["memory"]["id"]
        embs = (await s.execute(select(MemoryEmbedding))).scalars().all()
        assert len(embs) == 1
        assert embs[0].embedding_dimensions == 1536
        assert len(embs[0].vector) == 1536


@pytest.mark.asyncio
async def test_reject_candidate(client, session_factory) -> None:
    cand = await _seed_candidate(client)

    resp = await client.post(f"/v1/memory-candidates/{cand['id']}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    async with session_factory() as s:
        memories = (await s.execute(select(Memory))).scalars().all()
        assert memories == []


@pytest.mark.asyncio
async def test_cannot_confirm_already_resolved(client) -> None:
    cand = await _seed_candidate(client)
    first = await client.post(f"/v1/memory-candidates/{cand['id']}/confirm")
    assert first.status_code == 201
    second = await client.post(f"/v1/memory-candidates/{cand['id']}/confirm")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "memory_candidate_already_resolved"


@pytest.mark.asyncio
async def test_cannot_reject_after_confirm(client) -> None:
    cand = await _seed_candidate(client)
    await client.post(f"/v1/memory-candidates/{cand['id']}/confirm")
    rej = await client.post(f"/v1/memory-candidates/{cand['id']}/reject")
    assert rej.status_code == 409


@pytest.mark.asyncio
async def test_cross_user_cannot_confirm_candidate(client, as_user, user_a, user_b) -> None:
    as_user(user_a)
    cand = await _seed_candidate(client)

    as_user(user_b)
    await client.post("/v1/twin", json={"name": "B"})
    resp = await client.post(f"/v1/memory-candidates/{cand['id']}/confirm")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "memory_candidate_not_found"


@pytest.mark.asyncio
async def test_cross_user_candidate_list_isolation(client, as_user, user_a, user_b) -> None:
    as_user(user_a)
    await _seed_candidate(client)

    as_user(user_b)
    await client.post("/v1/twin", json={"name": "B"})
    resp = await client.get("/v1/memory-candidates")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_confirm_memory_succeeds_when_embedding_provider_fails(
    client, session_factory
) -> None:
    """CRITICAL (Sprint 2 modification 1):

    If embedding generation fails, the Memory and MemorySource must still
    be created and the endpoint must still return 201.
    """
    cand = await _seed_candidate(client, content="I own a dog named Pepper.")

    # Swap the embedding provider for one that raises.
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[get_embedding_provider] = lambda: FailingEmbeddingProvider()
    try:
        resp = await client.post(f"/v1/memory-candidates/{cand['id']}/confirm")
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    # The Memory exists.
    assert body["memory"]["user_confirmed"] is True
    assert body["memory"]["content"] == "I own a dog named Pepper."
    # The candidate is marked confirmed.
    assert body["candidate"]["status"] == "confirmed"
    # The confirmation reports the embedding failure without failing.
    assert body["embedding_attached"] is False
    assert body["embedding_error"] == "RuntimeError"

    async with session_factory() as s:
        memories = (await s.execute(select(Memory))).scalars().all()
        assert len(memories) == 1
        sources = (await s.execute(select(MemorySource))).scalars().all()
        assert len(sources) == 1
        embs = (await s.execute(select(MemoryEmbedding))).scalars().all()
        assert embs == []
