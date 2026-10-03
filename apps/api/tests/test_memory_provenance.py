"""Memory provenance endpoint tests (Sprint 4 DF4).

`GET /v1/memories/{id}/provenance` surfaces the source message/conversation
and a bounded sanitized snippet to the mobile "Why does my Twin know this?"
screen.

These tests build the preconditions directly through the services
(bypassing the LLM extractor so the test is independent of its content):

1. Create a Twin.
2. Create a Conversation + one user Message under it.
3. Seed a pending MemoryCandidate linked to that message.
4. Confirm the candidate to get a Memory + MemorySource with
   source_message_id set.
5. Call `GET /v1/memories/{id}/provenance` and assert on the snippet.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.deps import (
    get_current_user,
    sessionmaker_dep,
)
from app.conversation.models import Message
from app.memory.schemas import PROVENANCE_SNIPPET_MAX_CHARS, MemoryCandidateDraft
from app.memory.service import MemoryService
from app.twin.service import TwinService


async def _create_twin(client) -> None:
    resp = await client.post("/v1/twin", json={"name": "Aurora"})
    assert resp.status_code == 201


async def _confirm_memory_from_message(client, message_text: str) -> str:
    """Create conversation+message, seed candidate linked to it, confirm it."""
    conv_resp = await client.post("/v1/conversations", json={"title": "x"})
    conv_id = conv_resp.json()["id"]

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    user_dep = app.dependency_overrides[get_current_user]
    user = (await user_dep()) if callable(user_dep) else user_dep
    sessionmaker = app.dependency_overrides[sessionmaker_dep]()

    async with sessionmaker() as session:
        # Create a user Message under the conversation directly so we don't
        # depend on the extractor's content heuristics.
        import uuid as _uuid

        msg = Message(
            id=_uuid.uuid4(),
            conversation_id=_uuid.UUID(conv_id),
            role="user",
            content=message_text,
        )
        session.add(msg)
        await session.flush()
        message_id = msg.id

        twin = await TwinService(session).require_by_user(user.user_id)
        service = MemoryService(session, embedding_provider=None)
        [cand] = await service.create_candidates(
            twin,
            [
                MemoryCandidateDraft(
                    type="FACT",
                    content="A deliberate seed for provenance test.",
                    confidence=0.9,
                    importance=0.5,
                )
            ],
            source_conversation_id=_uuid.UUID(conv_id),
            source_message_id=message_id,
        )
        candidate_id = cand.id

    confirm = await client.post(f"/v1/memory-candidates/{candidate_id}/confirm")
    assert confirm.status_code == 201, confirm.text
    return confirm.json()["memory"]["id"]


@pytest.mark.asyncio
async def test_provenance_returns_source_rows(client) -> None:
    await _create_twin(client)
    memory_id = await _confirm_memory_from_message(
        client, "I live in Bengaluru and I like filter coffee."
    )

    resp = await client.get(f"/v1/memories/{memory_id}/provenance")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["memory_id"] == memory_id
    assert body["sources"], "expected at least one source row"
    source = body["sources"][0]
    for field in (
        "source_id",
        "source_type",
        "source_message_id",
        "source_conversation_id",
        "created_at",
        "source_snippet",
        "source_snippet_truncated",
    ):
        assert field in source


@pytest.mark.asyncio
async def test_provenance_snippet_is_bounded(client) -> None:
    await _create_twin(client)
    long_text = (
        "I grew up in a small coastal town and I remember the exact smell "
        "of the salt on summer mornings. " * 10
    )
    memory_id = await _confirm_memory_from_message(client, long_text)

    body = (await client.get(f"/v1/memories/{memory_id}/provenance")).json()
    source = body["sources"][0]
    assert source["source_snippet"] is not None
    assert len(source["source_snippet"]) <= PROVENANCE_SNIPPET_MAX_CHARS + 1
    assert source["source_snippet_truncated"] is True


@pytest.mark.asyncio
async def test_provenance_short_message_not_truncated(client) -> None:
    await _create_twin(client)
    memory_id = await _confirm_memory_from_message(client, "I love ramen.")

    body = (await client.get(f"/v1/memories/{memory_id}/provenance")).json()
    source = body["sources"][0]
    assert source["source_snippet"] == "I love ramen."
    assert source["source_snippet_truncated"] is False


@pytest.mark.asyncio
async def test_provenance_unknown_memory_is_404(client) -> None:
    await _create_twin(client)
    import uuid

    resp = await client.get(f"/v1/memories/{uuid.uuid4()}/provenance")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "memory_not_found"


@pytest.mark.asyncio
async def test_provenance_cross_user_is_404(
    client, as_user, user_a, user_b
) -> None:
    as_user(user_a)
    await _create_twin(client)
    memory_id = await _confirm_memory_from_message(client, "A's private fact.")

    as_user(user_b)
    resp = await client.get(f"/v1/memories/{memory_id}/provenance")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] in {"memory_not_found", "twin_not_found"}


@pytest.mark.asyncio
async def test_provenance_snippet_none_when_message_missing(
    client, session_factory
) -> None:
    """If the source message is gone, the snippet is None (safe default).

    On Postgres the FK's ON DELETE SET NULL does this automatically; on
    SQLite (used in tests) we assert the same safe-default behaviour by
    hard-deleting the message row — the provenance lookup joins to
    `messages` and returns `None` when the join finds nothing.
    """
    await _create_twin(client)
    memory_id = await _confirm_memory_from_message(client, "Soon-deleted text.")

    async with session_factory() as session:
        for msg in (await session.execute(select(Message))).scalars():
            await session.delete(msg)
        await session.commit()

    body = (await client.get(f"/v1/memories/{memory_id}/provenance")).json()
    assert body["sources"][0]["source_snippet"] is None
