"""Runtime configuration.

Every setting is sourced from the environment. Nothing is hard-coded that
belongs in configuration. See `.env.example` at the repo root.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)

# SQLAlchemy needs an explicit async driver; the app only ever speaks asyncpg.
_ASYNC_PG_SCHEME = "postgresql+asyncpg"

# Query parameters libpq understands but asyncpg does not. SQLAlchemy forwards
# unknown query parameters to ``asyncpg.connect()`` as keyword arguments, so
# leaving these in raises TypeError at the first connection instead of
# connecting.
_LIBPQ_ONLY_PARAMS = frozenset({"sslmode", "channel_binding", "gssencmode", "target_session_attrs"})


class Settings(BaseSettings):
    """Immutable, cached settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Runtime ----
    app_env: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    # Commit the running build was made from. Render sets RENDER_GIT_COMMIT on
    # every git-backed deploy; surfaced by /v1/system/version so a deploy can
    # be checked against the commit that was tested.
    git_commit: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GIT_COMMIT", "RENDER_GIT_COMMIT"),
    )
    # Interactive API docs. Public by default; set false to hide the schema.
    api_docs_enabled: bool = True

    # ---- Database ----
    database_url: str = "sqlite+aiosqlite:///:memory:"
    # Pool sizing is per process. pool_size + max_overflow is the hard ceiling
    # on concurrent database work, and every chat turn holds one connection
    # for the duration of its LLM call.
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=200)
    # How long a request waits for a free connection before failing with 503.
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    # Serverless Postgres (Neon) suspends idle computes and drops their
    # connections; recycle below the suspend window and pre-ping on checkout.
    db_pool_recycle_seconds: int = Field(default=240, ge=30)
    db_connect_timeout_seconds: float = Field(default=15.0, gt=0)
    db_command_timeout_seconds: float = Field(default=30.0, gt=0)

    # ---- Supabase Auth ----
    supabase_jwt_jwks_url: str | None = None
    supabase_jwt_audience: str | None = "authenticated"
    supabase_jwt_hs_secret: str | None = None
    # When set, the token's `iss` claim must equal this value exactly.
    supabase_jwt_issuer: str | None = None

    # ---- LLM ----
    llm_provider: str = "mock"
    llm_model: str = "mock-echo"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    # Per-attempt deadline. The SDK retries timeouts, so the worst case is
    # roughly llm_timeout_seconds * (llm_max_retries + 1).
    llm_timeout_seconds: float = Field(default=45.0, gt=0, le=600)
    llm_max_retries: int = Field(default=1, ge=0, le=5)
    # Ceiling on generated tokens, thinking included. Callers ask for the
    # visible answer size they need; the provider never goes below this so a
    # model that thinks before answering is not cut off mid-reply.
    llm_max_tokens: int = Field(default=16000, ge=256, le=128000)
    # Reasoning effort for models that accept it. Unset = the model default.
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    # "auto": on models that support it, a safety-classifier decline is
    # retried server-side on a fallback model. "off": a decline is final.
    llm_refusal_fallback: Literal["auto", "off"] = "auto"
    # Mock provider only: delay every reply by this long, so a load test
    # holds connections the way a real model call does.
    mock_llm_latency_ms: int = Field(default=0, ge=0, le=60_000)

    # ---- Abuse protection ----
    # None = on everywhere except the test environment.
    rate_limit_enabled: bool | None = None
    # Per authenticated user, per minute.
    rate_limit_default_per_minute: int = Field(default=120, ge=1)
    rate_limit_chat_per_minute: int = Field(default=20, ge=1)
    rate_limit_ai_per_minute: int = Field(default=6, ge=1)
    # Per client IP, per minute, applied before authentication.
    rate_limit_ip_per_minute: int = Field(default=300, ge=1)
    # Largest request body accepted, in bytes. The biggest legitimate payload
    # is an 8,000-character chat message.
    max_request_body_bytes: int = Field(default=65_536, ge=1024)

    # ---- Embeddings (Sprint 2+; declared here so config is stable) ----
    embedding_provider: str = "mock"
    embedding_model: str = "mock-embed-1"
    embedding_dimensions: int = 1536

    # ---- Reflection scheduler (Sprint 8 Evolving Twin Loop) ----
    # These thresholds drive `OpportunityPolicy`. All four are
    # intentionally conservative: they prefer SKIP over noisy
    # reflections. See docs/architecture/evolving-twin-loop.md.
    #
    # Sprint 8.1 hardening: each threshold has a server-side SAFETY
    # FLOOR enforced at construction time via `Field(ge=…)` / `le=…`.
    # A misconfigured deployment that tries to lower a threshold below
    # the approved Sprint-8 default will fail Settings() construction
    # with a pydantic.ValidationError — the app refuses to boot rather
    # than silently generate noisy reflections and spend LLM budget.
    # The floors ARE the shipped defaults; raising a threshold (making
    # it more conservative) is still permitted.
    #
    # Belt-and-braces: `OpportunityPolicy.__post_init__` applies the
    # same floors to defend against direct construction that bypasses
    # Settings (tests, workers).
    reflection_min_new_memories: int = Field(default=3, ge=3)
    reflection_min_goal_events: int = Field(default=2, ge=2)
    reflection_min_cooldown_seconds: int = Field(default=1800, ge=1800)
    reflection_max_pending_backlog: int = Field(default=10, ge=1, le=100)

    # ---- CORS ----
    cors_allow_origins: str = "http://localhost:8081,http://localhost:19006"

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Accept the URL shape managed Postgres providers actually hand out.

        Render, Railway, Heroku and Fly all expose ``postgres://…``, usually
        with ``?sslmode=require``. Neither form is usable here: the runtime
        validator requires a ``postgresql`` scheme, SQLAlchemy requires an
        explicit async driver, and asyncpg rejects libpq-only parameters.
        Normalising at the edge means DATABASE_URL can be injected verbatim
        from any provider's secret store, so the deployed URL is never
        hand-edited (and so never silently wrong after a password rotation).

        Non-PostgreSQL URLs (the SQLite test fixtures) are returned untouched.
        """
        if "://" not in value:
            return value
        scheme, rest = value.split("://", 1)
        if scheme.split("+", 1)[0].lower() not in {"postgres", "postgresql"}:
            return value
        # An explicitly chosen driver is honoured; only a bare scheme is filled in.
        new_scheme = scheme if "+" in scheme else _ASYNC_PG_SCHEME
        if "?" in rest:
            location, query = rest.split("?", 1)
            kept: list[tuple[str, str]] = []
            for key, val in parse_qsl(query, keep_blank_values=True):
                lowered = key.lower()
                if lowered == "sslmode":
                    # asyncpg spells this "ssl"; the values line up.
                    kept.append(("ssl", val))
                elif lowered not in _LIBPQ_ONLY_PARAMS:
                    kept.append((key, val))
            rest = location + (f"?{urlencode(kept)}" if kept else "")
        return f"{new_scheme}://{rest}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def rate_limit_active(self) -> bool:
        if self.rate_limit_enabled is None:
            return self.app_env != "test"
        return self.rate_limit_enabled


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency: return the singleton Settings instance."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cache. Test-only."""
    get_settings.cache_clear()


class ConfigurationError(RuntimeError):
    """Raised at startup when staging/prod configuration is unsafe or
    incomplete. Carries a human-actionable message and never a secret
    value."""


# LLM providers that only ever make sense in local dev / tests. Selecting
# one of these in staging/prod would silently turn the Twin into an echo
# bot, so the validator rejects them rather than booting "healthy".
_DEV_ONLY_LLM_PROVIDERS: frozenset[str] = frozenset({"mock", "local"})

# Every provider name the LLM registry has a factory for. Kept in sync with
# ``app.llm.registry._LLM_FACTORIES``. A value outside this set means the
# operator typo'd ``LLM_PROVIDER`` — a hard startup failure, since nothing
# else in the app can recover from an unknown provider name.
_KNOWN_LLM_PROVIDERS: frozenset[str] = frozenset({"mock", "local", "anthropic", "openai"})

_PRODUCTION_ENVS: frozenset[str] = frozenset({"staging", "prod"})


def validate_runtime_config() -> None:
    """Fail fast in staging/prod on unsafe or incomplete configuration.

    In ``dev``/``test`` the database and embedding checks are skipped so
    local development and the test suite keep working with mock/local
    providers and SQLite fixtures — but a real ``LLM_PROVIDER`` selected
    there must still be constructible, so a missing SDK or API key fails at
    startup instead of 500-ing on the first chat. It does nothing at import
    time or during unit-test collection — it runs only when called from the
    application lifespan (see ``app.main``).

    Reuses the existing provider registry as the single source of truth for
    "which provider needs which SDK / credential": it simply constructs the
    configured providers and lets the registry raise its own clear errors.
    Never includes a secret value (or the full ``DATABASE_URL``) in the
    message — only the URL scheme and curated registry errors.
    """
    settings = get_settings()
    if settings.app_env not in _PRODUCTION_ENVS:
        # dev/test stay permissive about SQLite and the mock/local providers.
        # An UNKNOWN provider name is still a hard failure here (typo in
        # .env.dev would otherwise silently boot), but a known real provider
        # with missing SDK/credentials is a WARNING, not a raise — parity
        # with the prod behaviour below, and AI endpoints return 503 until
        # credentials are supplied.
        provider_name = settings.llm_provider
        if (
            provider_name not in _DEV_ONLY_LLM_PROVIDERS
            and provider_name not in _KNOWN_LLM_PROVIDERS
        ):
            raise ConfigurationError(
                f"Refusing to start: LLM_PROVIDER={provider_name!r} is not a "
                "known provider (expected one of: anthropic, openai, mock, local)."
            )
        if provider_name not in _DEV_ONLY_LLM_PROVIDERS and provider_name in _KNOWN_LLM_PROVIDERS:
            from app.llm.registry import get_llm_provider as _get_llm_provider

            try:
                _get_llm_provider()
            except Exception as exc:
                _logger.warning(
                    "api.config.llm_degraded provider=%s detail=%s",
                    provider_name,
                    exc,
                )
        return

    # Lazy import to avoid a config <-> registry import cycle.
    from app.llm.registry import get_embedding_provider, get_llm_provider

    problems: list[str] = []

    # ---- Database: must be real PostgreSQL, never SQLite/in-memory ----
    db_url = settings.database_url
    scheme = db_url.split("://", 1)[0] if "://" in db_url else db_url
    if db_url.startswith("sqlite") or ":memory:" in db_url:
        problems.append(
            "DATABASE_URL is a SQLite/in-memory URL; staging/prod requires a "
            "PostgreSQL asyncpg URL (postgresql+asyncpg://…). Running on "
            "in-memory SQLite would silently lose all data on restart."
        )
    elif not scheme.startswith("postgresql"):
        problems.append(
            f"DATABASE_URL scheme {scheme!r} is not PostgreSQL; staging/prod "
            "requires postgresql+asyncpg://…"
        )

    # ---- LLM provider: name must be known; credentials are a soft check ----
    #
    # Historically a missing LLM API key was a hard startup failure, on the
    # reasoning that booting "healthy" and 500-ing every chat is worse than
    # not booting at all. That was correct when chat was the only surface,
    # but the app now also serves health, docs, auth, Twin CRUD and
    # conversation history — none of which need the LLM. Refusing to boot
    # also traps already-applied migrations behind an un-rollback-able
    # deploy. So: the provider NAME is still validated strictly here (a
    # typo'd or dev-only value stays a hard failure), while a missing SDK
    # or API key for an otherwise-real provider is logged as a WARNING and
    # the app comes up in a degraded state. AI-dependent endpoints then
    # return a controlled 503 from the registry until the key is set, and
    # operators can save the key and let Render redeploy without rolling
    # back the DB.
    provider_name = settings.llm_provider
    if provider_name in _DEV_ONLY_LLM_PROVIDERS:
        problems.append(
            f"LLM_PROVIDER={provider_name!r} is development-only; "
            "staging/prod requires a real provider (e.g. 'anthropic')."
        )
    elif provider_name not in _KNOWN_LLM_PROVIDERS:
        problems.append(
            f"LLM_PROVIDER={provider_name!r} is not a known provider "
            "(expected one of: anthropic, openai)."
        )
    else:
        try:
            get_llm_provider()
        except Exception as exc:  # registry/provider raise curated, secret-free messages
            _logger.warning(
                "api.config.llm_degraded provider=%s detail=%s",
                provider_name,
                exc,
            )

    # ---- Embedding provider: the configured one must be constructible ----
    # Mock embeddings are permitted (best-effort retrieval) but warned about,
    # since they silently degrade semantic memory retrieval in production.
    try:
        get_embedding_provider()
    except Exception as exc:
        problems.append(f"Embedding provider {settings.embedding_provider!r} is not usable: {exc}")

    if problems:
        raise ConfigurationError(
            "Refusing to start: unsafe or incomplete "
            f"{settings.app_env} configuration.\n- " + "\n- ".join(problems)
        )
