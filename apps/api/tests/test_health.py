"""Health and system endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client) -> None:
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_version_shape(client) -> None:
    resp = await client.get("/v1/system/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api"] == "v1"
    assert body["env"] == "test"
    assert body["llm_provider"] == "mock"
    assert body["llm_model"] == "mock-echo"
    assert "version" in body
