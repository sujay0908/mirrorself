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
