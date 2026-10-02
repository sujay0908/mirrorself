"""End-to-end integration test.

user → auth → create twin → conversation → message → response → reopen.
Covers the definition-of-done items 1–8 of Sprint 1.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_vertical_slice(client) -> None:
    # 1–2. Authenticated user (via fixture) has no Twin yet.
    resp = await client.get("/v1/twin")
    assert resp.status_code == 404

    # 3. Create the Twin (and profile in one call).
    created = await client.post(
        "/v1/twin",
        json={
            "name": "Nova",
            "communication_style": "terse",
            "basic_profile": {"favourite_colour": "green"},
        },
    )
    assert created.status_code == 201
    twin = created.json()
    assert twin["profile"]["communication_style_preset"] == "terse"

    # 4. Open a conversation.
    conv = (
        await client.post("/v1/conversations", json={"title": "Sprint 1"})
    ).json()

    # 5–7. Send a message; twin responds; both persist.
    pair = await client.post(
        f"/v1/conversations/{conv['id']}/messages",
        json={"content": "Nice to meet you."},
    )
    assert pair.status_code == 201
    body = pair.json()
    assert body["user_message"]["content"] == "Nice to meet you."
    assert body["twin_message"]["content"].startswith("twin(mock):")

    # 8. Reopen conversation — history is intact.
    msgs = (await client.get(f"/v1/conversations/{conv['id']}/messages")).json()["items"]
    assert [m["role"] for m in msgs] == ["user", "twin"]

    # Ownership: user cannot see anyone else's twin (single-user test — the
    # cross-user case is covered in test_conversations.py).
