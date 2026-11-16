"""Small integrity guarantees: races, ordering ties, payload bounds, and
reads that must not drag large columns along."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from app.evolution.service import EvolutionService
from app.memory.models import Memory, MemoryEmbedding
from app.memory.service import MemoryService
from app.twin.errors import TwinAlreadyExistsError
from app.twin.models import Twin, TwinProfile
from app.twin.schemas import BASIC_PROFILE_MAX_BYTES, BASIC_PROFILE_MAX_KEYS, TwinCreateIn
from app.twin.service import TwinService

# ---------------------------------------------------------------------
# Twin creation
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_twin_is_a_conflict(client) -> None:
    assert (await client.post("/v1/twin", json={"name": "Aurora"})).status_code == 201
    again = await client.post("/v1/twin", json={"name": "Nova"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "twin_already_exists"


@pytest.mark.asyncio
async def test_racing_twin_creates_end_in_a_conflict_not_a_500(
    session_factory, monkeypatch
) -> None:
    """Two creates for one user both pass the existence check (a double tap
    on the onboarding button). The unique constraint lets one through; the
    other must report the ordinary conflict."""
    user_id = uuid.uuid4()
    async with session_factory() as s:
        await TwinService(s).create(user_id, TwinCreateIn(name="First"))

    async with session_factory() as s:
        service = TwinService(s)

        async def _saw_nothing(_user_id: uuid.UUID) -> None:
            return None

        # Simulate having read "no twin yet" just before the other request
        # committed its insert.
        monkeypatch.setattr(service, "get_by_user", _saw_nothing)
        with pytest.raises(TwinAlreadyExistsError):
            await service.create(user_id, TwinCreateIn(name="Second"))

    async with session_factory() as s:
        twins = (await s.execute(select(Twin).where(Twin.user_id == user_id))).scalars().all()
        assert [t.display_name for t in twins] == ["First"]


@pytest.mark.asyncio
async def test_basic_profile_entry_count_is_bounded(client) -> None:
    too_many = {f"k{i}": i for i in range(BASIC_PROFILE_MAX_KEYS + 1)}
    resp = await client.post("/v1/twin", json={"name": "Aurora", "basic_profile": too_many})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_basic_profile_size_is_bounded(client) -> None:
    # The profile is rendered into every prompt, so its size is paid for on
    # every single chat turn.
    huge = {"bio": "x" * (BASIC_PROFILE_MAX_BYTES + 1)}
    resp = await client.post("/v1/twin", json={"name": "Aurora", "basic_profile": huge})
    assert resp.status_code == 422
    assert "x" * 100 not in resp.text

    await client.post("/v1/twin", json={"name": "Aurora"})
    patched = await client.patch("/v1/twin", json={"basic_profile": huge})
    assert patched.status_code == 422


@pytest.mark.asyncio
async def test_an_ordinary_profile_is_accepted(client) -> None:
    profile = {"city": "Bengaluru", "languages": ["en", "te"], "age": 30}
    resp = await client.post("/v1/twin", json={"name": "Aurora", "basic_profile": profile})
    assert resp.status_code == 201
    assert resp.json()["profile"]["basic_profile"] == profile


# ---------------------------------------------------------------------
# Evolution ordering
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evolution_is_newest_first_even_when_timestamps_tie(session_factory) -> None:
    """Events written by one confirmation share a clock reading. Ordering by
    time and then by a random id returned them shuffled; the per-twin
    sequence cannot tie."""
    async with session_factory() as s:
        twin = Twin(user_id=uuid.uuid4(), display_name="Aurora")
        twin.profile = TwinProfile()
        s.add(twin)
        await s.flush()
        service = EvolutionService(s)
        rows = [
            await service.record(twin, event_type="memory_learned", summary=f"event {i}")
            for i in range(12)
        ]
        # Force the worst case: every row has exactly the same timestamp.
        for row in rows:
            row.created_at = rows[0].created_at
        await s.commit()

        listed = await service.list_for_twin(twin, limit=5)
        assert [e.summary for e in listed] == [f"event {i}" for i in (11, 10, 9, 8, 7)]


# ---------------------------------------------------------------------
# Memory listing does not load vectors
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_memories_does_not_load_embedding_vectors(session_factory) -> None:
    """Each embedding row carries 1536 floats twice. The list endpoint
    returns only the model name and size, so it must not read them."""
    vector = [0.25] * 1536
    async with session_factory() as s:
        twin = Twin(user_id=uuid.uuid4(), display_name="Aurora")
        twin.profile = TwinProfile()
        s.add(twin)
        await s.flush()
        memory = Memory(
            user_id=twin.user_id,
            twin_id=twin.id,
            type="FACT",
            source="candidate_confirmation",
            content="I live in Bengaluru.",
            importance=0.5,
            confidence=0.9,
            user_confirmed=True,
        )
        s.add(memory)
        await s.flush()
        s.add(
            MemoryEmbedding(
                memory_id=memory.id,
                embedding_model="mock-embed-1",
                embedding_dimensions=1536,
                vector=vector,
                embedding_vector=vector,
            )
        )
        await s.commit()
        twin_id = twin.id

    async with session_factory() as s:
        twin = (await s.execute(select(Twin).where(Twin.id == twin_id))).scalar_one()
        memories = await MemoryService(s).list_for_twin(twin)
        assert len(memories) == 1
        embedding = memories[0].embeddings[0]
        # The metadata the API returns is there...
        assert embedding.embedding_model == "mock-embed-1"
        assert embedding.embedding_dimensions == 1536
        # ...and neither copy of the vector was fetched.
        unloaded = sa_inspect(embedding).unloaded
        assert {"vector", "embedding_vector"} <= unloaded

        one = await MemoryService(s).get(twin, memories[0].id)
        assert {"vector", "embedding_vector"} <= sa_inspect(one.embeddings[0]).unloaded


@pytest.mark.asyncio
async def test_memory_list_response_never_contains_a_vector(client, session_factory) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    async with session_factory() as s:
        twin = (await s.execute(select(Twin))).scalar_one()
        memory = Memory(
            user_id=twin.user_id,
            twin_id=twin.id,
            type="FACT",
            source="candidate_confirmation",
            content="I like filter coffee.",
            importance=0.5,
            confidence=0.9,
            user_confirmed=True,
        )
        s.add(memory)
        await s.flush()
        s.add(
            MemoryEmbedding(
                memory_id=memory.id,
                embedding_model="mock-embed-1",
                embedding_dimensions=1536,
                vector=[0.125] * 1536,
                embedding_vector=[0.125] * 1536,
            )
        )
        await s.commit()

    resp = await client.get("/v1/memories")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["embeddings"][0]["embedding_dimensions"] == 1536
    assert "0.125" not in resp.text
    assert len(json.dumps(resp.json())) < 5_000
