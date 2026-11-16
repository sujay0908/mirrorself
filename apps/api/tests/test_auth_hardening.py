"""Token verification edge cases: expiry, issuer, algorithm, key rotation.

Every key here is generated for the test run. Nothing is a project key.
"""

from __future__ import annotations

import base64
import time
import uuid
from collections.abc import Callable, Iterator

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.auth import supabase as supabase_auth
from app.config import reset_settings_cache
from app.main import create_app

JWKS_URL = "https://example.test/.well-known/jwks.json"
ISSUER = "https://example.test/auth/v1"


def _keypair(kid: str) -> tuple[str, dict[str, str]]:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    numbers = key.public_key().public_numbers()

    def b64(value: int) -> str:
        return base64.urlsafe_b64encode(value.to_bytes(32, "big")).rstrip(b"=").decode()

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


def _token(pem: str, kid: str, **claims: object) -> str:
    payload: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "exp": int(time.time()) + 300,
    }
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, pem, algorithm="ES256", headers={"kid": kid})


@pytest.fixture
def jwks_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., AsyncClient]]:
    """An app verifying against a JWKS document the test controls."""
    published: dict[str, list[dict[str, str]]] = {"keys": []}
    fetches = {"count": 0}

    def _fetch(_url: str) -> dict[str, list[dict[str, str]]]:
        fetches["count"] += 1
        return {"keys": list(published["keys"])}

    monkeypatch.setattr(supabase_auth, "_fetch_jwks", _fetch)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SUPABASE_JWT_JWKS_URL", JWKS_URL)
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    reset_settings_cache()

    def _client() -> AsyncClient:
        transport = ASGITransport(app=create_app(), raise_app_exceptions=False)
        return AsyncClient(transport=transport, base_url="http://test")

    _client.published = published  # type: ignore[attr-defined]
    _client.fetches = fetches  # type: ignore[attr-defined]
    yield _client
    reset_settings_cache()


async def _status(client_factory: Callable[..., AsyncClient], token: str) -> tuple[int, dict]:
    async with client_factory() as c:
        # /v1/twin needs a database; an authenticated request that gets past
        # auth fails later for that reason, which is not what is under test.
        resp = await c.get("/v1/twin", headers={"Authorization": f"Bearer {token}"})
    return resp.status_code, resp.json()


@pytest.mark.asyncio
async def test_expired_token_is_rejected(jwks_app) -> None:
    pem, jwk = _keypair("k1")
    jwks_app.published["keys"] = [jwk]
    status, body = await _status(jwks_app, _token(pem, "k1", exp=int(time.time()) - 60))
    assert status == 401
    assert body["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_token_without_expiry_is_rejected(jwks_app) -> None:
    # A token that never expires is a permanent credential if it ever leaks.
    pem, jwk = _keypair("k1")
    jwks_app.published["keys"] = [jwk]
    status, _ = await _status(jwks_app, _token(pem, "k1", exp=None))
    assert status == 401


@pytest.mark.asyncio
async def test_wrong_audience_is_rejected(jwks_app) -> None:
    pem, jwk = _keypair("k1")
    jwks_app.published["keys"] = [jwk]
    status, _ = await _status(jwks_app, _token(pem, "k1", aud="service_role"))
    assert status == 401


@pytest.mark.asyncio
async def test_rejection_does_not_say_which_check_failed(jwks_app) -> None:
    pem, jwk = _keypair("k1")
    jwks_app.published["keys"] = [jwk]
    _, expired = await _status(jwks_app, _token(pem, "k1", exp=int(time.time()) - 60))
    _, wrong_aud = await _status(jwks_app, _token(pem, "k1", aud="other"))
    assert expired["error"]["message"] == wrong_aud["error"]["message"]
    assert "expired" not in expired["error"]["message"].lower().replace("or expired", "")


@pytest.mark.asyncio
async def test_issuer_is_enforced_when_configured(jwks_app, monkeypatch) -> None:
    pem, jwk = _keypair("k1")
    jwks_app.published["keys"] = [jwk]
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", ISSUER)
    reset_settings_cache()

    other_project, _ = await _status(jwks_app, _token(pem, "k1", iss="https://other.test/auth/v1"))
    assert other_project == 401
    missing, _ = await _status(jwks_app, _token(pem, "k1"))
    assert missing == 401
    # The matching issuer gets past auth (and then fails on the absent
    # database, which is fine here: it is no longer a 401).
    matching, _ = await _status(jwks_app, _token(pem, "k1", iss=ISSUER))
    assert matching != 401


@pytest.mark.asyncio
async def test_symmetric_algorithm_in_jwks_is_never_honoured(jwks_app) -> None:
    # If a JWKS entry could select HS256, the public key material would
    # become a shared secret anyone could sign with.
    pem, jwk = _keypair("k1")
    jwks_app.published["keys"] = [{**jwk, "alg": "HS256"}]
    status, body = await _status(jwks_app, _token(pem, "k1"))
    assert status == 401
    assert body["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_keys_are_cached_between_requests(jwks_app) -> None:
    pem, jwk = _keypair("k1")
    jwks_app.published["keys"] = [jwk]
    for _ in range(5):
        await _status(jwks_app, _token(pem, "k1"))
    assert jwks_app.fetches["count"] == 1


@pytest.mark.asyncio
async def test_key_rotation_is_picked_up_without_a_restart(jwks_app, monkeypatch) -> None:
    old_pem, old_jwk = _keypair("old")
    new_pem, new_jwk = _keypair("new")
    jwks_app.published["keys"] = [old_jwk]
    assert (await _status(jwks_app, _token(old_pem, "old")))[0] != 401

    # The project rotates: tokens now name a key the cache has never seen.
    jwks_app.published["keys"] = [old_jwk, new_jwk]

    # Inside the refetch floor the unknown key id is simply rejected...
    assert (await _status(jwks_app, _token(new_pem, "new")))[0] == 401
    assert jwks_app.fetches["count"] == 1

    # ...and once the floor has passed, the cache refreshes and it verifies.
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        supabase_auth.time,
        "monotonic",
        lambda: real_monotonic() + supabase_auth._JWKS_MIN_REFETCH_SECONDS + 1,
    )
    assert (await _status(jwks_app, _token(new_pem, "new")))[0] != 401
    assert jwks_app.fetches["count"] == 2


@pytest.mark.asyncio
async def test_unknown_key_ids_cannot_cause_a_fetch_storm(jwks_app) -> None:
    pem, jwk = _keypair("k1")
    other_pem, _ = _keypair("nope")
    jwks_app.published["keys"] = [jwk]
    await _status(jwks_app, _token(pem, "k1"))
    for i in range(10):
        status, _ = await _status(jwks_app, _token(other_pem, f"made-up-{i}"))
        assert status == 401
    assert jwks_app.fetches["count"] == 1


@pytest.mark.asyncio
async def test_unreachable_identity_provider_is_a_503_not_a_500(jwks_app, monkeypatch) -> None:
    pem, _ = _keypair("k1")

    def _down(_url: str) -> dict:
        raise ConnectionError("identity provider unreachable")

    monkeypatch.setattr(supabase_auth, "_fetch_jwks", _down)
    status, body = await _status(jwks_app, _token(pem, "k1"))
    assert status == 503
    assert body["error"]["code"] == "auth_unavailable"


@pytest.mark.asyncio
async def test_cached_keys_survive_an_identity_provider_outage(jwks_app, monkeypatch) -> None:
    pem, jwk = _keypair("k1")
    jwks_app.published["keys"] = [jwk]
    assert (await _status(jwks_app, _token(pem, "k1")))[0] != 401

    def _down(_url: str) -> dict:
        raise ConnectionError("identity provider unreachable")

    # Age the cache past its lifetime, then take the provider away.
    monkeypatch.setattr(supabase_auth, "_fetch_jwks", _down)
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        supabase_auth.time,
        "monotonic",
        lambda: real_monotonic() + supabase_auth._JWKS_TTL_SECONDS + 1,
    )
    # Signed-in users keep working on the keys already held.
    assert (await _status(jwks_app, _token(pem, "k1")))[0] != 401
