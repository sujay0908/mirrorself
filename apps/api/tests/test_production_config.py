"""Production startup-validation tests (P0 hardening).

`validate_runtime_config()` must fail fast in staging/prod on unsafe or
incomplete configuration — SQLite/in-memory databases, dev-only or
misconfigured providers — instead of booting "healthy" and failing on the
first chat request. In dev/test it must be a no-op so the existing mock +
SQLite fixtures keep working.

These construct `Settings` purely from environment variables (via the real
`get_settings()` singleton) and never use real credentials.
"""

from __future__ import annotations

import pytest

from app.config import (
    ConfigurationError,
    get_settings,
    reset_settings_cache,
    validate_runtime_config,
)
from app.llm import registry as llm_registry


@pytest.fixture(autouse=True)
def _reset_caches() -> object:
    """Each test sets its own env; start and end from a clean settings +
    provider cache so one test's config never leaks into another."""
    reset_settings_cache()
    llm_registry.reset_provider_cache()
    yield
    reset_settings_cache()
    llm_registry.reset_provider_cache()


def _set_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    reset_settings_cache()
    llm_registry.reset_provider_cache()


_POSTGRES_URL = "postgresql+asyncpg://user:pw@db.example.com:5432/app"


def test_prod_rejects_in_memory_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="prod",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="anthropic",
        EMBEDDING_PROVIDER="mock",
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    assert "SQLite" in str(excinfo.value)
    # The raw DATABASE_URL (which could carry a password) must never be echoed.
    assert "sqlite+aiosqlite:///:memory:" not in str(excinfo.value)


def test_prod_rejects_non_postgres_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="prod",
        DATABASE_URL="mysql+aiomysql://user:pw@db/app",
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY="x",  # force past the LLM check onto the DB finding
        EMBEDDING_PROVIDER="mock",
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    assert "PostgreSQL" in str(excinfo.value)
    # Only the scheme may appear, never the credentials in the netloc.
    assert "pw@db" not in str(excinfo.value)


def test_prod_accepts_valid_postgres_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid Postgres URL + usable providers passes with no error.

    The providers are stubbed so the test needs no real SDK or key — the
    point here is that a correct DB URL is accepted (the registry's own
    SDK/credential checks are exercised in the rejection tests below).
    """
    _set_env(
        monkeypatch,
        APP_ENV="prod",
        DATABASE_URL=_POSTGRES_URL,
        LLM_PROVIDER="anthropic",
        EMBEDDING_PROVIDER="openai",
    )
    monkeypatch.setattr(llm_registry, "get_llm_provider", lambda: object())
    monkeypatch.setattr(llm_registry, "get_embedding_provider", lambda: object())
    # Must not raise.
    validate_runtime_config()


def test_prod_rejects_missing_llm_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # anthropic selected but no ANTHROPIC_API_KEY → registry raises before it
    # ever needs the SDK, so this is deterministic without the SDK installed.
    _set_env(
        monkeypatch,
        APP_ENV="prod",
        DATABASE_URL=_POSTGRES_URL,
        LLM_PROVIDER="anthropic",
        EMBEDDING_PROVIDER="mock",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    msg = str(excinfo.value)
    assert "LLM provider 'anthropic' is not usable" in msg
    assert "ANTHROPIC_API_KEY" in msg


def test_prod_rejects_missing_embedding_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="prod",
        DATABASE_URL=_POSTGRES_URL,
        LLM_PROVIDER="anthropic",
        EMBEDDING_PROVIDER="openai",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Stub the LLM so only the embedding credential problem surfaces.
    monkeypatch.setattr(llm_registry, "get_llm_provider", lambda: object())
    reset_settings_cache()
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    msg = str(excinfo.value)
    assert "Embedding provider 'openai' is not usable" in msg
    assert "OPENAI_API_KEY" in msg


def test_prod_rejects_unsupported_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="prod",
        DATABASE_URL=_POSTGRES_URL,
        LLM_PROVIDER="banana",
        EMBEDDING_PROVIDER="mock",
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    assert "banana" in str(excinfo.value)


def test_prod_rejects_dev_only_mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="prod",
        DATABASE_URL=_POSTGRES_URL,
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    assert "development-only" in str(excinfo.value)


def test_dev_config_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    # The default local-dev shape: SQLite + mock providers must pass.
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
    )
    validate_runtime_config()  # no raise


def test_test_env_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="test",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
    )
    validate_runtime_config()  # no raise
    assert get_settings().app_env == "test"


# ---- dev: a REAL provider must still be usable at startup ----------------
#
# Local dev may select `anthropic`, so the no-op-in-dev rule cannot extend to
# the provider credential check: without this, the API boots "healthy" and
# every chat 500s. None of these use a real key.


def test_dev_rejects_real_llm_provider_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="anthropic",
        EMBEDDING_PROVIDER="mock",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    msg = str(excinfo.value)
    assert "LLM_PROVIDER='anthropic'" in msg
    assert "ANTHROPIC_API_KEY" in msg


def test_dev_accepts_real_llm_provider_once_credentials_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The key is never used to call anything here: the registry only needs a
    # non-empty value to construct the provider. Stubbed so the test does not
    # depend on the vendor SDK being installed.
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="anthropic",
        EMBEDDING_PROVIDER="mock",
        ANTHROPIC_API_KEY="placeholder-not-a-real-key",
    )
    monkeypatch.setattr(llm_registry, "get_llm_provider", lambda: object())
    validate_runtime_config()  # no raise


def test_dev_rejects_unknown_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="anthropik",  # typo in .env.dev must not boot silently
        EMBEDDING_PROVIDER="mock",
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    assert "anthropik" in str(excinfo.value)


def test_dev_still_skips_the_database_and_embedding_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SQLite + an uncredentialed embedding provider stay legal in dev; only
    # the LLM provider check was added.
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="openai",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    validate_runtime_config()  # no raise


def test_local_provider_stays_a_dev_only_shortcut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 'local' is an unimplemented stub, so it must not be treated as real and
    # must not be credential-checked in dev.
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="local",
        EMBEDDING_PROVIDER="mock",
    )
    validate_runtime_config()  # no raise


# --------------------------------------------------------------------------
# DATABASE_URL NORMALISATION
#
# Managed Postgres providers (Render, Railway, Heroku, Fly) expose
# `postgres://…`, usually with `?sslmode=require`. That URL is unusable as
# given: the production validator demands a `postgresql` scheme, SQLAlchemy
# demands an explicit async driver, and asyncpg raises TypeError on libpq-only
# query parameters. Normalising lets the provider's secret store be injected
# verbatim.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Bare provider scheme gets the async driver.
        (
            "postgres://u:p@h:5432/db",
            "postgresql+asyncpg://u:p@h:5432/db",
        ),
        (
            "postgresql://u:p@h:5432/db",
            "postgresql+asyncpg://u:p@h:5432/db",
        ),
        # libpq's sslmode is translated to the name asyncpg uses.
        (
            "postgres://u:p@h:5432/db?sslmode=require",
            "postgresql+asyncpg://u:p@h:5432/db?ssl=require",
        ),
        # libpq-only parameters asyncpg cannot accept are dropped.
        (
            "postgres://u:p@h/db?channel_binding=require&target_session_attrs=rw",
            "postgresql+asyncpg://u:p@h/db",
        ),
        # An explicit driver is the caller's choice and is left alone.
        (
            "postgresql+asyncpg://u:p@h/db",
            "postgresql+asyncpg://u:p@h/db",
        ),
        # Non-PostgreSQL URLs (the test fixtures) are untouched.
        (
            "sqlite+aiosqlite:///:memory:",
            "sqlite+aiosqlite:///:memory:",
        ),
    ],
)
def test_database_url_is_normalised_for_managed_providers(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL=raw,
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
    )
    assert get_settings().database_url == expected


def test_normalisation_preserves_unrelated_query_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="postgres://u:p@h/db?application_name=twin&sslmode=require",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
    )
    url = get_settings().database_url
    assert url.startswith("postgresql+asyncpg://u:p@h/db?")
    assert "application_name=twin" in url
    assert "ssl=require" in url
    assert "sslmode" not in url


def test_a_providers_raw_url_now_satisfies_production_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the whole exercise: a URL copied straight out of a
    provider's secret store must pass prod validation, not be rejected for
    its scheme."""
    _set_env(
        monkeypatch,
        APP_ENV="prod",
        DATABASE_URL="postgres://u:p@h:5432/db?sslmode=require",
        LLM_PROVIDER="mock",  # still dev-only -> prod must still reject THIS
        EMBEDDING_PROVIDER="mock",
    )
    with pytest.raises(ConfigurationError) as excinfo:
        validate_runtime_config()
    message = str(excinfo.value)
    # The database is no longer a complaint; only the dev-only LLM provider is.
    assert "DATABASE_URL" not in message
    assert "development-only" in message


# --------------------------------------------------------------------------
# CORS ORIGINS
#
# A browser origin missing from this list is not a server error: the request
# is rejected by the browser, the API logs nothing unusual, and the frontend
# reports only that it cannot reach the API. The deployed frontend origin
# therefore has to survive parsing exactly as written.
# --------------------------------------------------------------------------


def test_multiple_cors_origins_are_split(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed = "https://mirrorself-web.vercel.app,https://timeismetime.com"
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
        CORS_ALLOW_ORIGINS=deployed,
    )
    assert get_settings().cors_origins_list == [
        "https://mirrorself-web.vercel.app",
        "https://timeismetime.com",
    ]


def test_cors_origins_tolerate_whitespace_and_empty_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
        CORS_ALLOW_ORIGINS=" https://a.example ,, https://b.example , ",
    )
    assert get_settings().cors_origins_list == [
        "https://a.example",
        "https://b.example",
    ]


def test_cors_origin_is_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    # An origin is scheme + host + port and nothing else. A trailing slash or
    # a path would never match a browser's Origin header.
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
        CORS_ALLOW_ORIGINS="https://mirrorself-web.vercel.app",
    )
    origins = get_settings().cors_origins_list
    assert origins == ["https://mirrorself-web.vercel.app"]
    assert not origins[0].endswith("/")


def test_local_dev_origins_remain_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(
        monkeypatch,
        APP_ENV="dev",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
    )
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    reset_settings_cache()
    assert get_settings().cors_origins_list == [
        "http://localhost:8081",
        "http://localhost:19006",
    ]
