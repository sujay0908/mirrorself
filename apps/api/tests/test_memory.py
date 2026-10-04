"""Memory CRUD and ownership rules."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.memory.models import Memory, MemoryEmbedding, MemorySource


async def _seed_candidate_and_confirm(
    client, type_: str = "FACT", content: str = "I live in Bengaluru."
) -> dict:
    """Create a Twin, a candidate via the service directly, then confirm it
    via HTTP to produce a Memory row. Returns the memory JSON.
    """
    # Create twin via HTTP.
    await client.post("/v1/twin", json={"name": "Aurora"})
    # Reach into the app to create a candidate directly through the service.
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    from app.api.deps import (
        get_current_user,
        sessionmaker_dep,
    )
    from app.llm.providers.mock_embedding import MockEmbeddingProvider
    from app.memory.schemas import MemoryCandidateDraft

    user = app.dependency_overrides[get_current_user]
    user = (await user()) if callable(user) else user
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()
    async with sessionmaker() as session:
        from app.memory.service import MemoryService
        from app.twin.service import TwinService

        twin_service = TwinService(session)
        twin = await twin_service.require_by_user(user.user_id)
        mem_service = MemoryService(
            session,
            embedding_provider=MockEmbeddingProvider(dimensions=16, model="t"),
        )
        [candidate] = await mem_service.create_candidates(
            twin,
            [MemoryCandidateDraft(type=type_, content=content, confidence=0.9, importance=0.8)],
        )
    # Confirm via HTTP.
    resp = await client.post(f"/v1/memory-candidates/{candidate.id}/confirm")
    assert resp.status_code == 201, resp.text
    return resp.json()["memory"]


@pytest.mark.asyncio
async def test_list_memories_empty_initially(client) -> None:
    await client.post("/v1/twin", json={"name": "A"})
    resp = await client.get("/v1/memories")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_list_memories_requires_twin(client) -> None:
    resp = await client.get("/v1/memories")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "twin_not_found"


@pytest.mark.asyncio
async def test_get_memory_404_when_missing(client) -> None:
    await client.post("/v1/twin", json={"name": "A"})
    resp = await client.get("/v1/memories/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_memory_updates_content_and_importance(client) -> None:
    memory = await _seed_candidate_and_confirm(client)
    resp = await client.patch(
        f"/v1/memories/{memory['id']}",
        json={
            "content": "I live in Mumbai.",
            "importance": 0.5,
            "metadata": {"corrected_at": "2026-10-01T00:00:00Z"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "I live in Mumbai."
    assert body["importance"] == 0.5
    assert body["metadata_json"]["corrected_at"] == "2026-10-01T00:00:00Z"


@pytest.mark.asyncio
async def test_patch_rejects_user_confirmed_field(client) -> None:
    """PATCH /v1/memories/{id} must not accept `user_confirmed`.

    Pydantic drops unknown fields by default under our model config, so the
    PATCH either succeeds while ignoring the field or 422s — either way,
    user_confirmed must NOT change in storage.
    """
    memory = await _seed_candidate_and_confirm(client)
    assert memory["user_confirmed"] is True
    # Attempt to flip it to False via PATCH; the field is simply not in the
    # schema and must have zero effect.
    resp = await client.patch(
        f"/v1/memories/{memory['id']}",
        json={"user_confirmed": False, "content": "edit"},
    )
    assert resp.status_code == 200
    assert resp.json()["user_confirmed"] is True


@pytest.mark.asyncio
async def test_delete_memory_removes_row_and_embedding(client, session_factory) -> None:
    memory = await _seed_candidate_and_confirm(client)
    memory_id = memory["id"]

    # Confirm the memory has an embedding row (mock provider succeeded).
    async with session_factory() as s:
        emb_rows = (await s.execute(select(MemoryEmbedding))).scalars().all()
        assert any(str(e.memory_id) == memory_id for e in emb_rows)

    resp = await client.delete(f"/v1/memories/{memory_id}")
    assert resp.status_code == 204

    async with session_factory() as s:
        remaining_memories = (await s.execute(select(Memory))).scalars().all()
        assert all(str(m.id) != memory_id for m in remaining_memories)
        remaining_sources = (await s.execute(select(MemorySource))).scalars().all()
        assert all(str(s.memory_id) != memory_id for s in remaining_sources)
        remaining_embs = (await s.execute(select(MemoryEmbedding))).scalars().all()
        assert all(str(e.memory_id) != memory_id for e in remaining_embs)


@pytest.mark.asyncio
async def test_cross_user_cannot_access_memory(client, as_user, user_a, user_b) -> None:
    as_user(user_a)
    memory = await _seed_candidate_and_confirm(client)

    as_user(user_b)
    await client.post("/v1/twin", json={"name": "B"})
    resp = await client.get(f"/v1/memories/{memory['id']}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "memory_not_found"

    resp = await client.patch(f"/v1/memories/{memory['id']}", json={"content": "intrusion"})
    assert resp.status_code == 404

    resp = await client.delete(f"/v1/memories/{memory['id']}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_memories_filters_by_type(client) -> None:
    await _seed_candidate_and_confirm(client, type_="FACT", content="One FACT.")
    await _seed_candidate_and_confirm(client, type_="PREFERENCE", content="One PREFERENCE.")

    all_resp = await client.get("/v1/memories")
    assert len(all_resp.json()["items"]) == 2

    only_facts = await client.get("/v1/memories?type=FACT")
    items = only_facts.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "FACT"
