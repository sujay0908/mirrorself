"""Chat MUST succeed even when memory retrieval fails.

This is a Sprint 3 architectural invariant (section 19.F): retrieval is
enrichment, not a hard dependency. A broken EmbeddingProvider for
retrieval must not break the chat path.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
import structlog
from sqlalchemy import select

from app.api.deps import get_embedding_provider
from app.conversation.models import Message
from app.llm.interface import EmbeddingProvider, EmbeddingRequest, EmbeddingResponse


class BrokenEmbeddingProvider(EmbeddingProvider):
    """Always raises on embed() to simulate a dead embedding provider."""

    provider_name: ClassVar[str] = "broken-embed"
    _default_model = "broken-embed-model"

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise RuntimeError("embedding provider intentionally broken for test")


@pytest.mark.asyncio
async def test_retrieval_failure_does_not_fail_chat(client, session_factory) -> None:
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app

    # Chat uses MockProvider (default). Only the embedding path is broken.
    app.dependency_overrides[get_embedding_provider] = lambda: BrokenEmbeddingProvider()
    secret_phrase = "quokka-paradox-sprint3"

    try:
        await client.post("/v1/twin", json={"name": "Aurora"})
        conv = (await client.post("/v1/conversations", json={"title": "t"})).json()

        with structlog.testing.capture_logs() as captured:
            resp = await client.post(
                f"/v1/conversations/{conv['id']}/messages",
                json={"content": f"I just moved to {secret_phrase} last month."},
            )
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)

    # 1. Chat still returns 201.
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_message"]["role"] == "user"
    assert body["twin_message"]["role"] == "twin"

    # 2. Both messages persisted.
    async with session_factory() as s:
        msgs = (await s.execute(select(Message))).scalars().all()
        assert len(msgs) == 2
        assert sorted(m.role for m in msgs) == ["twin", "user"]

    # 3. Retrieval failure is observable in structured telemetry.
    failure_events = [e for e in captured if e.get("event") == "memory.retrieval.failed"]
    assert failure_events, f"Expected memory.retrieval.failed event. Captured: {captured!r}"
    ev = failure_events[0]
    assert "RuntimeError" in str(ev.get("reason", ""))
    assert "twin_id" in ev
    assert "conversation_id" in ev
    assert ev["log_level"] in {"warning", "error"}

    # 4. SAFETY: user content must not leak into any log event.
    for e in captured:
        for value in e.values():
            if isinstance(value, str):
                assert secret_phrase not in value, f"user content leaked into log event: {e!r}"


@pytest.mark.asyncio
async def test_retrieval_metadata_recorded_on_twin_message(client, session_factory) -> None:
    """The twin message's metadata_json must record whether retrieval ran
    OK and how many memories were returned — this is the audit trail for
    'what did the LLM see?' at request time.
    """
    await client.post("/v1/twin", json={"name": "Aurora"})
    conv = (await client.post("/v1/conversations", json={"title": "t"})).json()
    posted = await client.post(
        f"/v1/conversations/{conv['id']}/messages",
        json={"content": "some substantive content."},
    )
    assert posted.status_code == 201

    async with session_factory() as s:
        twin_msg = (
            (await s.execute(select(Message).where(Message.role == "twin"))).scalars().first()
        )
        assert twin_msg is not None
        meta = twin_msg.metadata_json
        assert "retrieval" in meta
        assert meta["retrieval"]["ok"] is True
        assert meta["retrieval"]["memories_returned"] == 0
        assert meta["retrieval"]["memory_ids"] == []
