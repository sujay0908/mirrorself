"""Runtime configuration.

Every setting is sourced from the environment. Nothing is hard-coded that
belongs in configuration. See `.env.example` at the repo root.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

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
