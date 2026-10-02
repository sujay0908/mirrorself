"""Authentication dependency behaviour.

We test the real `get_current_user` path (which parses the Authorization
header and calls `verify_supabase_jwt`) by NOT overriding it. For happy-path
tests elsewhere the fixture-overridden version is used.
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.api.deps import db_session_dep
from app.config import reset_settings_cache
from app.main import create_app


@pytest.mark.asyncio
async def test_missing_bearer_returns_401(client) -> None:
    # Even though the fixture overrides get_current_user, dropping the override
    # for this one test proves the real dependency rejects missing headers.
    from app.api.deps import get_current_user

    app_and_client = client
    # `client` is the AsyncClient; the app is reachable via its transport.
    transport = app_and_client._transport  # type: ignore[attr-defined]
    app = transport.app  # type: ignore[attr-defined]
    app.dependency_overrides.pop(get_current_user, None)

    resp = await client.get("/v1/twin")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_bad_bearer_scheme_returns_401(client) -> None:
    from app.api.deps import get_current_user

    transport = client._transport  # type: ignore[attr-defined]
    app = transport.app  # type: ignore[attr-defined]
    app.dependency_overrides.pop(get_current_user, None)

    resp = await client.get("/v1/twin", headers={"Authorization": "Basic xyz"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_hs256_dev_secret_accepts_valid_token(session_factory) -> None:
    """Prove the HS256 dev shortcut actually verifies a well-formed token."""

    os.environ["APP_ENV"] = "dev"
    os.environ["SUPABASE_JWT_HS_SECRET"] = "test-secret-for-unit-tests-only"
    os.environ["SUPABASE_JWT_AUDIENCE"] = "authenticated"
    reset_settings_cache()

    try:
        app = create_app()

        async def _override_session():
            async with session_factory() as s:
                try:
                    yield s
                finally:
                    await s.close()

        app.dependency_overrides[db_session_dep] = _override_session

        sub_id = str(uuid.uuid4())
        token = jwt.encode(
            {"sub": sub_id, "aud": "authenticated", "email": "hs@example.com"},
            "test-secret-for-unit-tests-only",
            algorithm="HS256",
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # No Twin yet → 404, but the auth layer accepted the token.
            resp = await c.get(
                "/v1/twin", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "twin_not_found"
    finally:
        os.environ["APP_ENV"] = "test"
        os.environ.pop("SUPABASE_JWT_HS_SECRET", None)
        reset_settings_cache()
