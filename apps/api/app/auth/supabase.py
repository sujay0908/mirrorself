"""Supabase JWT verification.

Two modes:

1. **JWKS mode (staging + prod):** verify asymmetric signatures (ES256 or
   RS256) against the JWKS URL published by the Supabase project
   (`SUPABASE_JWT_JWKS_URL`). Keys are cached in-process and re-fetched when
   they age out or when a token names a key id the cache has not seen, so a
   signing-key rotation is picked up without a restart.
2. **HS mode (local dev only):** verify HS256 tokens with a shared secret
   (`SUPABASE_JWT_HS_SECRET`). Never enabled outside `app_env = "dev"`.

Verification uses PyJWT. python-jose, used before, has an unfixed advisory
(CVE-2026-85394: public keys accepted as HMAC secrets) and depends on
python-ecdsa, which has an unfixed timing side channel.

Tests bypass this file entirely by overriding the `get_current_user`
dependency with a fixture; see `tests/conftest.py`.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
import jwt

from app.auth.models import AuthenticatedUser
from app.common.errors import ServiceUnavailableError, UnauthorizedError
from app.config import Settings
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Asymmetric algorithms only. A JWKS entry that claimed a symmetric algorithm
# would let the public key be used as an HMAC secret, so it is never honoured.
_JWKS_ALGORITHMS = frozenset({"ES256", "RS256"})

_JWKS_TTL_SECONDS = 3600.0
# Floor between refetches triggered by an unknown key id, so a stream of
# tokens with made-up ids cannot turn this service into a JWKS request storm.
_JWKS_MIN_REFETCH_SECONDS = 30.0
# Tolerated clock difference between the identity provider and this server.
_LEEWAY_SECONDS = 10

# url -> (fetched_at, jwks document)
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _fetch_jwks(url: str) -> dict[str, Any]:
    """Blocking fetch of the JWKS document. Runs in a worker thread."""
    resp = httpx.get(url, timeout=5.0)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def reset_jwks_cache() -> None:
    """Forget cached signing keys. Test-only."""
    _jwks_cache.clear()


async def _load_jwks(url: str) -> dict[str, Any]:
    try:
        jwks = await asyncio.to_thread(_fetch_jwks, url)
    except Exception as exc:
        cached = _jwks_cache.get(url)
        if cached is not None:
            # The identity provider is unreachable but the keys we already
            # hold are still the right ones far more often than not.
            logger.warning("auth.jwks_refresh_failed", error_type=type(exc).__name__)
            return cached[1]
        logger.error("auth.jwks_unavailable", error_type=type(exc).__name__)
        raise ServiceUnavailableError(
            "Sign-in verification is temporarily unavailable. Please try again shortly.",
            code="auth_unavailable",
            headers={"Retry-After": "5"},
        ) from exc
    _jwks_cache[url] = (time.monotonic(), jwks)
    return jwks


def _find_key(jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    return next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)


async def _signing_key(url: str, kid: str | None) -> dict[str, Any] | None:
    cached = _jwks_cache.get(url)
    now = time.monotonic()
    if cached is None or now - cached[0] > _JWKS_TTL_SECONDS:
        return _find_key(await _load_jwks(url), kid)
    key = _find_key(cached[1], kid)
    if key is None and now - cached[0] > _JWKS_MIN_REFETCH_SECONDS:
        # Unknown key id on a warm cache: the project may have rotated keys.
        key = _find_key(await _load_jwks(url), kid)
    return key


def _decode_kwargs(settings: Settings) -> dict[str, Any]:
    return {
        "audience": settings.supabase_jwt_audience,
        "issuer": settings.supabase_jwt_issuer,
        "leeway": _LEEWAY_SECONDS,
        "options": {
            "require": ["exp", "sub"],
            "verify_aud": settings.supabase_jwt_audience is not None,
        },
    }


def _decode_hs(token: str, settings: Settings) -> dict[str, Any]:
    assert settings.supabase_jwt_hs_secret is not None
    return jwt.decode(
        token,
        settings.supabase_jwt_hs_secret,
        algorithms=["HS256"],
        **_decode_kwargs(settings),
    )


async def _decode_asymmetric(token: str, settings: Settings) -> dict[str, Any]:
    assert settings.supabase_jwt_jwks_url is not None
    unverified_header = jwt.get_unverified_header(token)
    key = await _signing_key(settings.supabase_jwt_jwks_url, unverified_header.get("kid"))
    if key is None:
        raise UnauthorizedError("Unknown token key.", code="unauthorized")
    algorithm = key.get("alg", "RS256")
    if algorithm not in _JWKS_ALGORITHMS:
        raise UnauthorizedError("Unsupported token algorithm.", code="unauthorized")
    signing_key = jwt.PyJWK(key, algorithm=algorithm).key
    return jwt.decode(
        token,
        signing_key,
        algorithms=[algorithm],
        **_decode_kwargs(settings),
    )


async def verify_supabase_jwt(token: str, settings: Settings) -> AuthenticatedUser:
    """Decode and verify a Supabase-issued JWT. Raises `UnauthorizedError`."""
    if not token:
        raise UnauthorizedError("Missing bearer token.")
    try:
        if settings.supabase_jwt_jwks_url:
            claims = await _decode_asymmetric(token, settings)
        elif settings.supabase_jwt_hs_secret and settings.app_env == "dev":
            claims = _decode_hs(token, settings)
        else:
            raise UnauthorizedError(
                "Auth not configured: set SUPABASE_JWT_JWKS_URL (or SUPABASE_JWT_HS_SECRET in dev)."
            )
    except jwt.PyJWTError as exc:
        # The library's reason (expired, bad signature, wrong audience) is
        # logged for operators and deliberately not returned: it tells an
        # attacker which check to work on next.
        logger.info("auth.token_rejected", reason=type(exc).__name__)
        raise UnauthorizedError("Invalid or expired token.") from exc

    sub = claims.get("sub")
    if not sub:
        raise UnauthorizedError("Token missing 'sub' claim.")

    try:
        supabase_id = uuid.UUID(str(sub))
    except ValueError as exc:
        raise UnauthorizedError("Token 'sub' is not a UUID.") from exc

    return AuthenticatedUser(supabase_id=supabase_id, email=claims.get("email"))
