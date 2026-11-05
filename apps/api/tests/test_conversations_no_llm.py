"""Conversation endpoints must work without an LLM key — except post_message.

Production dropped to 503 on every `/v1/conversations*` call once
ANTHROPIC_API_KEY was removed, including the four pure-DB routes (create,
list, retrieve, list-messages) that never touch the LLM. Root cause: the
service's FastAPI dep hard-depended on `get_llm_provider`, which raises
`ProviderNotConfiguredError` (503) when no provider is usable, and FastAPI
resolves dependencies before the handler body runs.

The fix uses an `OptionalLLMProviderDep` that catches ONLY
`ProviderNotConfiguredError` and passes `None` through, and
`ConversationService.post_message` refuses the request at the TOP of the
method so a key-less POST cannot leave an orphan user-message row behind.

These tests pin both halves of the invariant:
  * all non-AI conversation endpoints succeed with the LLM dep returning None
  * post_message returns the 503 envelope and persists ZERO new rows
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.api.deps import (
    extraction_llm_provider_dep,
    get_llm_provider,
    optional_extraction_llm_provider_dep,
    optional_llm_provider_dep,
)
from app.conversation.models import Conversation, Message


def _simulate_missing_llm(client) -> None:
    """Make every LLM dependency behave as if no provider is configured.

    Overrides both the hard `get_llm_provider` (used by non-conversation
    routes like `POST /v1/reflections/run`) and the optional variants
    (used by `ConversationServiceDep`), so a single test exercises the
    exact production state: ANTHROPIC_API_KEY unset.
    """
    from app.llm.registry import ProviderNotConfiguredError

    def _raise_not_configured() -> None:
        raise ProviderNotConfiguredError("ANTHROPIC_API_KEY is not set but LLM_PROVIDER=anthropic.")

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    app.dependency_overrides[get_llm_provider] = _raise_not_configured
    app.dependency_overrides[optional_llm_provider_dep] = lambda: None
    app.dependency_overrides[optional_extraction_llm_provider_dep] = lambda: None
    # Both sides of extraction_llm_provider_dep have to map to None too,
    # so a stray hard reference does not resurrect the eager 503.
    app.dependency_overrides[extraction_llm_provider_dep] = lambda: None


def _restore_llm(client) -> None:
    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app
    for dep in (
        get_llm_provider,
        optional_llm_provider_dep,
        optional_extraction_llm_provider_dep,
        extraction_llm_provider_dep,
    ):
        app.dependency_overrides.pop(dep, None)


async def _seed_twin_and_conversation(client, *, with_llm: bool = True) -> str:
    """Create the twin + one conversation with a real provider, then
    optionally drop the LLM for subsequent calls. Returns the
    conversation id.

    The seed itself does not need the LLM, but creating the twin + the
    conversation BEFORE simulating the missing key matches the
    production shape the user hit (`/home` already shows a Twin and the
    page then fails to list conversations).
    """
    await client.post("/v1/twin", json={"name": "sujay"})
    created = await client.post("/v1/conversations", json={"title": "First"})
    assert created.status_code == 201, created.text
    conv_id: str = created.json()["id"]
    if not with_llm:
        _simulate_missing_llm(client)
    return conv_id


# ---------------------------------------------------------------------
# NON-AI ROUTES: must succeed without a usable LLM provider
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_conversation_works_without_llm(client) -> None:
    await client.post("/v1/twin", json={"name": "sujay"})
    _simulate_missing_llm(client)

    resp = await client.post("/v1/conversations", json={"title": "Hello"})

    assert resp.status_code == 201, resp.text
    assert resp.json()["title"] == "Hello"
    _restore_llm(client)


@pytest.mark.asyncio
async def test_list_conversations_works_without_llm(client) -> None:
    """The production symptom: /home calls GET /v1/conversations and 503s."""
    conv_id = await _seed_twin_and_conversation(client, with_llm=False)

    resp = await client.get("/v1/conversations")

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert any(c["id"] == conv_id for c in items)
    _restore_llm(client)


@pytest.mark.asyncio
async def test_retrieve_conversation_works_without_llm(client) -> None:
    conv_id = await _seed_twin_and_conversation(client, with_llm=False)

    resp = await client.get(f"/v1/conversations/{conv_id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == conv_id
    _restore_llm(client)


@pytest.mark.asyncio
async def test_list_messages_works_without_llm(client) -> None:
    conv_id = await _seed_twin_and_conversation(client, with_llm=True)
    # Post one real message with the LLM up, so there is history to list.
    await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "Hello, twin!"},
    )
    _simulate_missing_llm(client)

    resp = await client.get(f"/v1/conversations/{conv_id}/messages")

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [m["role"] for m in items] == ["user", "twin"]
    _restore_llm(client)


# ---------------------------------------------------------------------
# AI ROUTE: must return 503 with the stable envelope AND persist nothing
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_message_returns_503_without_llm(client) -> None:
    conv_id = await _seed_twin_and_conversation(client, with_llm=False)

    resp = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "Hi"},
    )

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["error"]["code"] == "llm_provider_not_configured"
    # The error message must never carry a credential value.
    assert "placeholder" not in body["error"]["message"]
    assert "ANTHROPIC_API_KEY" in body["error"]["message"]
    _restore_llm(client)


@pytest.mark.asyncio
async def test_post_message_without_llm_persists_no_rows(client, session_factory) -> None:
    """The 503 must happen BEFORE any DB write — no orphan user messages.

    This is the whole reason `post_message` checks `_provider is None` at
    the top of the method rather than letting the pipeline raise. If the
    user message were persisted first, the conversation would gain a
    permanent user turn with no twin reply, which the mobile UI has no
    way to resolve.
    """
    conv_id = await _seed_twin_and_conversation(client, with_llm=False)
    conv_uuid = uuid.UUID(conv_id)

    async with session_factory() as s:
        before = (
            (
                await s.execute(
                    select(Message).join(Conversation).where(Conversation.id == conv_uuid)
                )
            )
            .scalars()
            .all()
        )
        assert len(before) == 0

    resp = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "ghost"},
    )
    assert resp.status_code == 503, resp.text

    async with session_factory() as s:
        after = (
            (
                await s.execute(
                    select(Message).join(Conversation).where(Conversation.id == conv_uuid)
                )
            )
            .scalars()
            .all()
        )
        assert len(after) == 0, (
            "post_message must refuse before writing the user turn; otherwise "
            "the conversation grows a user message with no twin reply."
        )
    _restore_llm(client)


@pytest.mark.asyncio
async def test_post_message_503_does_not_break_subsequent_reads(client) -> None:
    """The 503 must leave the conversation reachable for later reads."""
    conv_id = await _seed_twin_and_conversation(client, with_llm=False)

    fail = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "dropped"},
    )
    assert fail.status_code == 503

    # List, retrieve, and list-messages must all still work.
    assert (await client.get("/v1/conversations")).status_code == 200
    assert (await client.get(f"/v1/conversations/{conv_id}")).status_code == 200
    msgs = await client.get(f"/v1/conversations/{conv_id}/messages")
    assert msgs.status_code == 200
    assert msgs.json()["items"] == []
    _restore_llm(client)


# ---------------------------------------------------------------------
# EXTRACTION PROVIDER: absence must not break non-AI reads
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_absence_does_not_break_list(client) -> None:
    """Chat extraction runs in a background task AFTER post_message, so a
    missing extraction provider must not touch the synchronous
    GET /v1/conversations path. The dep passes None through, and nothing
    on the list path reads `_extraction_provider`."""
    conv_id = await _seed_twin_and_conversation(client, with_llm=False)

    resp = await client.get("/v1/conversations")

    assert resp.status_code == 200
    assert any(c["id"] == conv_id for c in resp.json()["items"])
    _restore_llm(client)
