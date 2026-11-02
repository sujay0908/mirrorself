"""Authentication dependency behaviour.

We test the real `get_current_user` path (which parses the Authorization
header and calls `verify_supabase_jwt`) by NOT overriding it. For happy-path
tests elsewhere the fixture-overridden version is used.
"""

from __future__ import annotations

import base64
import os
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.api.deps import db_session_dep
from app.config import reset_settings_cache
from app.main import create_app


def _es256_keypair(kid: str) -> tuple[str, dict[str, str]]:
    """An ephemeral P-256 keypair: (private PEM, public JWK).

    Generated per test run. Nothing here is a project key or a secret.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    numbers = key.public_key().public_numbers()

    def b64(value: int) -> str:
        raw = value.to_bytes(32, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "alg": "ES256",
        "use": "sig",
        "kid": kid,
        "x": b64(numbers.x),
        "y": b64(numbers.y),
    }
    return pem, jwk


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
            resp = await c.get("/v1/twin", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "twin_not_found"
    finally:
        os.environ["APP_ENV"] = "test"
        os.environ.pop("SUPABASE_JWT_HS_SECRET", None)
        reset_settings_cache()


@pytest.mark.asyncio
async def test_jwks_es256_token_is_accepted(session_factory, monkeypatch) -> None:
    """The JWKS path verifies an ES256 token against the published key.

    This is the mode local dev now runs in: the Supabase project signs
    access tokens with an asymmetric key (ES256) published at its JWKS
    endpoint, so the HS256 shared-secret path can never verify them and
    every authenticated request came back 401.
    """

    kid = "test-kid-es256"
    private_pem, public_jwk = _es256_keypair(kid)

    monkeypatch.setattr(
        "app.auth.supabase._fetch_jwks",
        lambda _url: {"keys": [public_jwk]},
    )
    os.environ["APP_ENV"] = "dev"
    os.environ["SUPABASE_JWT_JWKS_URL"] = "https://example.test/.well-known/jwks.json"
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

        token = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "aud": "authenticated",
                "email": "es256@example.com",
            },
            private_pem,
            algorithm="ES256",
            headers={"kid": kid},
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/v1/twin", headers={"Authorization": f"Bearer {token}"})

        # No Twin for this subject yet -> 404. The point is that it is NOT 401:
        # the signature, algorithm and audience all verified.
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "twin_not_found"
    finally:
        os.environ["APP_ENV"] = "test"
        os.environ.pop("SUPABASE_JWT_JWKS_URL", None)
        reset_settings_cache()


@pytest.mark.asyncio
async def test_jwks_rejects_token_signed_by_another_key(
    session_factory, monkeypatch
) -> None:
    """A token whose kid is not in the JWKS is rejected, not waved through."""

    _, published_jwk = _es256_keypair("published-kid")
    attacker_pem, _ = _es256_keypair("other-kid")

    monkeypatch.setattr(
        "app.auth.supabase._fetch_jwks",
        lambda _url: {"keys": [published_jwk]},
    )
    os.environ["APP_ENV"] = "dev"
    os.environ["SUPABASE_JWT_JWKS_URL"] = "https://example.test/.well-known/jwks.json"
    reset_settings_cache()

    try:
        app = create_app()
        token = jwt.encode(
            {"sub": str(uuid.uuid4()), "aud": "authenticated"},
            attacker_pem,
            algorithm="ES256",
            headers={"kid": "other-kid"},
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/v1/twin", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"
    finally:
        os.environ["APP_ENV"] = "test"
        os.environ.pop("SUPABASE_JWT_JWKS_URL", None)
        reset_settings_cache()


@pytest.mark.asyncio
async def test_hs_secret_is_ignored_once_jwks_is_configured(
    session_factory, monkeypatch
) -> None:
    """JWKS wins over a stale HS secret - the exact local-dev misconfiguration.

    .env.dev still carries a locally generated HS256 secret. With JWKS set,
    a token minted from that secret must NOT be accepted.
    """

    _, published_jwk = _es256_keypair("published-kid")
    monkeypatch.setattr(
        "app.auth.supabase._fetch_jwks",
        lambda _url: {"keys": [published_jwk]},
    )
    os.environ["APP_ENV"] = "dev"
    os.environ["SUPABASE_JWT_HS_SECRET"] = "stale-local-dev-secret-for-unit-tests"
    os.environ["SUPABASE_JWT_JWKS_URL"] = "https://example.test/.well-known/jwks.json"
    reset_settings_cache()

    try:
        app = create_app()
        token = jwt.encode(
            {"sub": str(uuid.uuid4()), "aud": "authenticated"},
            "stale-local-dev-secret-for-unit-tests",
            algorithm="HS256",
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/v1/twin", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
    finally:
        os.environ["APP_ENV"] = "test"
        os.environ.pop("SUPABASE_JWT_HS_SECRET", None)
        os.environ.pop("SUPABASE_JWT_JWKS_URL", None)
        reset_settings_cache()
