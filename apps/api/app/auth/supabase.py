"""Supabase JWT verification.

Two modes:

1. **JWKS mode (staging + prod):** verify RS256 signatures against the JWKS
   URL published by the Supabase project (`SUPABASE_JWT_JWKS_URL`). Keys are
   fetched once per process and cached.
2. **HS mode (local dev only):** verify HS256 tokens with a shared secret
   (`SUPABASE_JWT_HS_SECRET`). Never enabled outside `app_env = "dev"`.

Tests bypass this file entirely by overriding the `get_current_user`
dependency with a fixture; see `tests/conftest.py`.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

import httpx
from jose import JWTError, jwt

from app.auth.models import AuthenticatedUser
from app.common.errors import UnauthorizedError
from app.config import Settings


@lru_cache(maxsize=1)
def _fetch_jwks(url: str) -> dict[str, Any]:
    resp = httpx.get(url, timeout=5.0)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def _decode_hs(token: str, settings: Settings) -> dict[str, Any]:
    assert settings.supabase_jwt_hs_secret is not None
    return jwt.decode(  # type: ignore[no-any-return]
        token,
        settings.supabase_jwt_hs_secret,
        algorithms=["HS256"],
        audience=settings.supabase_jwt_audience,
        options={"verify_aud": settings.supabase_jwt_audience is not None},
    )


def _decode_rs(token: str, settings: Settings) -> dict[str, Any]:
    assert settings.supabase_jwt_jwks_url is not None
    jwks = _fetch_jwks(settings.supabase_jwt_jwks_url)
    unverified_header = jwt.get_unverified_header(token)
    key = next(
        (k for k in jwks.get("keys", []) if k.get("kid") == unverified_header.get("kid")),
        None,
    )
    if key is None:
        raise UnauthorizedError("Unknown token key.", code="unauthorized")
    return jwt.decode(  # type: ignore[no-any-return]
        token,
        key,
        algorithms=[key.get("alg", "RS256")],
        audience=settings.supabase_jwt_audience,
        options={"verify_aud": settings.supabase_jwt_audience is not None},
    )


def verify_supabase_jwt(token: str, settings: Settings) -> AuthenticatedUser:
    """Decode and verify a Supabase-issued JWT. Raises `UnauthorizedError`."""
    if not token:
        raise UnauthorizedError("Missing bearer token.")
    try:
        if settings.supabase_jwt_jwks_url:
            claims = _decode_rs(token, settings)
        elif settings.supabase_jwt_hs_secret and settings.app_env == "dev":
            claims = _decode_hs(token, settings)
        else:
            raise UnauthorizedError(
                "Auth not configured: set SUPABASE_JWT_JWKS_URL "
                "(or SUPABASE_JWT_HS_SECRET in dev)."
            )
    except JWTError as exc:
        raise UnauthorizedError(f"Invalid token: {exc}") from exc

    sub = claims.get("sub")
    if not sub:
        raise UnauthorizedError("Token missing 'sub' claim.")

    try:
        supabase_id = uuid.UUID(str(sub))
    except ValueError as exc:
        raise UnauthorizedError("Token 'sub' is not a UUID.") from exc

    return AuthenticatedUser(supabase_id=supabase_id, email=claims.get("email"))
