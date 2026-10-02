"""Conversation and message endpoints, including ownership isolation."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_full_conversation_flow(client) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    created = await client.post("/v1/conversations", json={"title": "First"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    listed = await client.get("/v1/conversations")
    assert listed.status_code == 200
    assert any(c["id"] == conversation_id for c in listed.json()["items"])

    posted = await client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": "Hello, twin!"},
    )
    assert posted.status_code == 201, posted.text
    body = posted.json()
    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == "Hello, twin!"
    assert body["twin_message"]["role"] == "twin"
    # Mock provider is deterministic.
    assert body["twin_message"]["content"] == "twin(mock): I heard you say: Hello, twin!"
    assert body["twin_message"]["llm_provider"] == "mock"
    assert body["twin_message"]["llm_model"] == "mock-echo"

    msgs = await client.get(f"/v1/conversations/{conversation_id}/messages")
    assert msgs.status_code == 200
    items = msgs.json()["items"]
    assert len(items) == 2
    assert [m["role"] for m in items] == ["user", "twin"]


@pytest.mark.asyncio
async def test_reopen_conversation_persists_history(client) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    conv = (await client.post("/v1/conversations", json={"title": "R"})).json()

    await client.post(
        f"/v1/conversations/{conv['id']}/messages", json={"content": "one"}
    )
    await client.post(
        f"/v1/conversations/{conv['id']}/messages", json={"content": "two"}
    )

    msgs = (await client.get(f"/v1/conversations/{conv['id']}/messages")).json()["items"]
    assert len(msgs) == 4  # user, twin, user, twin
    assert [m["content"] for m in msgs] == [
        "one",
        "twin(mock): I heard you say: one",
        "two",
        "twin(mock): I heard you say: two",
    ]


@pytest.mark.asyncio
async def test_cross_user_cannot_read_another_users_conversation(
    client, as_user, user_a, user_b
) -> None:
    as_user(user_a)
    await client.post("/v1/twin", json={"name": "A"})
    a_conv = (await client.post("/v1/conversations", json={"title": "a"})).json()

    as_user(user_b)
    await client.post("/v1/twin", json={"name": "B"})
    resp = await client.get(f"/v1/conversations/{a_conv['id']}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "conversation_not_found"


@pytest.mark.asyncio
async def test_cross_user_cannot_post_to_another_users_conversation(
    client, as_user, user_a, user_b
) -> None:
    as_user(user_a)
    await client.post("/v1/twin", json={"name": "A"})
    a_conv = (await client.post("/v1/conversations", json={"title": "a"})).json()

    as_user(user_b)
    await client.post("/v1/twin", json={"name": "B"})
    resp = await client.post(
        f"/v1/conversations/{a_conv['id']}/messages",
        json={"content": "intrusion"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_conversation_requires_twin(client) -> None:
    # No twin created yet.
    resp = await client.post("/v1/conversations", json={"title": "x"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "twin_not_found"
