"""Runtime configuration.

Every setting is sourced from the environment. Nothing is hard-coded that
belongs in configuration. See `.env.example` at the repo root.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ---- Database ----
    database_url: str = "sqlite+aiosqlite:///:memory:"

    # ---- Supabase Auth ----
    supabase_jwt_jwks_url: str | None = None
    supabase_jwt_audience: str | None = "authenticated"
    supabase_jwt_hs_secret: str | None = None

    # ---- LLM ----
    llm_provider: str = "mock"
    llm_model: str = "mock-echo"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency: return the singleton Settings instance."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cache. Test-only."""
    get_settings.cache_clear()
