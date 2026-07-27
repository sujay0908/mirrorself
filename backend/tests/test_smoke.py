"""Smoke tests for MirrorSelf backend.

These tests are intentionally light: they don't load torch / TTS, and they
override dependencies (LLM, voice, avatar) with stubs. The goal is to verify
that the wiring is correct — auth, DB, schema, and the chat pipeline glue —
without needing the heavy ML dependencies.
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


# Force test settings before importing the app.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-placeholder")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client():
    # Import inside the fixture so the env vars are set first.
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.anyio
async def test_unauthenticated_me_is_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.anyio
async def test_legacy_register_endpoint_returns_gone(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "username": "tester", "password": "supersecret123"},
    )
    assert r.status_code == 410


@pytest.mark.anyio
async def test_legacy_login_endpoint_returns_gone(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login", json={"email": "test@example.com", "password": "supersecret123"}
    )
    assert r.status_code == 410


@pytest.mark.anyio
async def test_bootstrap_requires_authentication(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "tester", "display_name": "Test User"},
    )
    assert r.status_code == 401


@pytest.mark.anyio
async def test_prompt_service_includes_personality() -> None:
    from app.services.prompt_service import build_system_prompt

    class _U:
        username = "alice"
        display_name = "Alice"
        personality = {
            "values": ["honesty", "craft"],
            "communication_style": "direct",
            "humor": "dry",
            "fears": ["regret"],
            "dreams": ["build a small thing"],
        }

    prompt = build_system_prompt(_U(), facts=[{"category": "personal", "content": "lives in Berlin"}], tone="playful")
    assert "honesty" in prompt
    assert "playful" in prompt.lower()
    assert "Berlin" in prompt


@pytest.mark.anyio
async def test_sentiment_quick_returns_tone() -> None:
    from app.services.sentiment import sentiment_analyzer

    r = sentiment_analyzer.quick("I am so happy today!!")
    assert r.emotion in {"joy", "neutral"}
    assert r.tone in {"playful", "neutral"}


@pytest.mark.anyio
async def test_memory_dedupes_similar_facts(client: AsyncClient) -> None:
    from app.services.memory_service import _tokens, _jaccard

    a = "I live in Berlin and love coffee"
    b = "I live in Berlin and love coffee."
    c = "I am a backend engineer"
    assert _jaccard(_tokens(a), _tokens(b)) > 0.7
    assert _jaccard(_tokens(a), _tokens(c)) < 0.3
