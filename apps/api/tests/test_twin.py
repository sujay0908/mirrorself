"""Twin creation, retrieval, editing, and ownership rules."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_twin_before_creation_returns_404(client) -> None:
    resp = await client.get("/v1/twin")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "twin_not_found"


@pytest.mark.asyncio
async def test_create_twin_and_read_it_back(client) -> None:
    create = await client.post(
        "/v1/twin",
        json={
            "name": "Aurora",
            "communication_style": "warm",
            "basic_profile": {"location": "Bengaluru"},
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["display_name"] == "Aurora"
    assert body["profile"]["communication_style_preset"] == "warm"
    assert body["profile"]["basic_profile"] == {"location": "Bengaluru"}
    twin_id = body["id"]

    read = await client.get("/v1/twin")
    assert read.status_code == 200
    assert read.json()["id"] == twin_id


@pytest.mark.asyncio
async def test_only_one_twin_per_user(client) -> None:
    first = await client.post("/v1/twin", json={"name": "One"})
    assert first.status_code == 201

    second = await client.post("/v1/twin", json={"name": "Two"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "twin_already_exists"


@pytest.mark.asyncio
async def test_patch_twin_updates_profile_fields(client) -> None:
    await client.post("/v1/twin", json={"name": "Aurora"})
    patched = await client.patch(
        "/v1/twin",
        json={
            "display_name": "Aurora Prime",
            "communication_style_preset": "analytical",
            "communication_style_notes": "Prefers structured answers.",
            "basic_profile": {"role": "founder"},
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["display_name"] == "Aurora Prime"
    assert body["profile"]["communication_style_preset"] == "analytical"
    assert body["profile"]["communication_style_notes"] == "Prefers structured answers."
    assert body["profile"]["basic_profile"] == {"role": "founder"}


@pytest.mark.asyncio
async def test_cross_user_cannot_access_other_users_twin(
    client, as_user, user_a, user_b
) -> None:
    as_user(user_a)
    a = await client.post("/v1/twin", json={"name": "A's Twin"})
    assert a.status_code == 201

    as_user(user_b)
    resp = await client.get("/v1/twin")
    # User B has no Twin, so 404 — and they cannot see A's Twin.
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_validation_error_shape(client) -> None:
    resp = await client.post("/v1/twin", json={})  # missing 'name'
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert "errors" in body["error"]["details"]
