"""
Application configuration loaded from environment variables.
"""
from functools import lru_cache
from typing import Any, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # App
    APP_NAME: str = "MirrorSelf"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3001"]

    # Security
    SECRET_KEY: str = "change-me-in-production-please-use-a-strong-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    BCRYPT_ROUNDS: int = 12

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://mirrorself:mirrorself@localhost:5432/mirrorself"
    DATABASE_URL_SYNC: str = "postgresql://mirrorself:mirrorself@localhost:5432/mirrorself"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MEMORY_TTL: int = 60 * 60 * 24 * 30  # 30 days for fact memory

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-5"
    CLAUDE_MAX_TOKENS: int = 1024

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_JWKS_URL: str = ""  # Optional: for local JWT verification in production

    # Google Cloud / Firebase Storage
    GCP_PROJECT_ID: str = ""
    FIREBASE_STORAGE_BUCKET: str = ""
    FIREBASE_STORAGE_URL_MODE: str = "firebase_token"  # firebase_token | signed_url | public_url
    STORAGE_URL_TTL_SECONDS: int = 3600
    STORAGE_FACE_PREFIX: str = "face-photos"
    STORAGE_VOICE_SAMPLES_PREFIX: str = "voice-samples"
    STORAGE_VOICE_OUTPUT_PREFIX: str = "voice-output"
    STORAGE_AVATARS_PREFIX: str = "avatars"

    # XTTS
    XTTS_MODEL_DIR: str = "./models/xtts"
    XTTS_DEVICE: str = "cuda"  # or "cpu"
    XTTS_SAMPLE_RATE: int = 24000
    VOICE_SAMPLES_DIR: str = "./storage/voice_samples"
    VOICE_OUTPUT_DIR: str = "./storage/voice_output"

    # SadTalker
    SADTALKER_DIR: str = "./models/SadTalker"
    SADTALKER_CHECKPOINTS: str = "./models/SadTalker/checkpoints"
    SADTALKER_DEVICE: str = "cuda"
    AVATAR_OUTPUT_DIR: str = "./storage/avatars"
    FACE_PHOTOS_DIR: str = "./storage/face_photos"

    # Storage
    UPLOAD_MAX_SIZE_MB: int = 50
    ALLOWED_IMAGE_TYPES: List[str] = ["image/jpeg", "image/png", "image/webp"]
    ALLOWED_AUDIO_TYPES: List[str] = ["audio/wav", "audio/mpeg", "audio/mp3", "audio/webm", "audio/ogg"]

    # Public URL (for sharing profiles)
    PUBLIC_BASE_URL: str = "http://localhost:3000"

    # Logging
    LOG_LEVEL: str = "INFO"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "production", "prod"}:
                return False
        return bool(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
