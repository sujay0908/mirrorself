"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import v1_router
from app.common.errors import register_exception_handlers
from app.config import get_settings, validate_runtime_config
from app.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    # Fail fast in staging/prod on unsafe/incomplete config (SQLite in
    # prod, missing real-provider SDK/credentials, unsupported provider)
    # rather than booting "healthy" and 500-ing on the first chat.
    # No-op in dev/test. Raises ConfigurationError → startup aborts.
    validate_runtime_config()
    if settings.app_env in ("staging", "prod") and settings.embedding_provider == "mock":
        logger.warning(
            "api.config.mock_embeddings_in_production",
            detail="EMBEDDING_PROVIDER=mock degrades semantic memory retrieval",
        )
    logger.info(
        "api.startup",
        version=__version__,
        env=settings.app_env,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
    )
    yield
    logger.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Personal AI Twin API",
        version=__version__,
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        openapi_url="/v1/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(v1_router, prefix="/v1")
    return app


app = create_app()
