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
from app.db.session import dispose_engine
from app.observability.logging import configure_logging, get_logger
from app.observability.middleware import RequestContextMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    # Fail fast in staging/prod on unsafe/incomplete config (SQLite in
    # prod, missing real-provider SDK/credentials, unsupported provider)
    # rather than booting "healthy" and 500-ing on the first chat. In
    # dev/test only the real-LLM-provider check runs.
    # Raises ConfigurationError → startup aborts.
    validate_runtime_config()
    if settings.app_env in ("staging", "prod") and settings.embedding_provider == "mock":
        logger.warning(
            "api.config.mock_embeddings_in_production",
            detail="EMBEDDING_PROVIDER=mock degrades semantic memory retrieval",
        )
    logger.info(
        "api.startup",
        version=__version__,
        commit=settings.git_commit,
        env=settings.app_env,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        rate_limiting=settings.rate_limit_active,
    )
    yield
    # Return pooled connections to the database instead of leaving them to
    # time out server-side on every deploy.
    await dispose_engine()
    logger.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    docs = settings.api_docs_enabled
    app = FastAPI(
        title="Personal AI Twin API",
        version=__version__,
        docs_url="/v1/docs" if docs else None,
        redoc_url="/v1/redoc" if docs else None,
        openapi_url="/v1/openapi.json" if docs else None,
        lifespan=lifespan,
    )

    # Order matters: the last middleware added is the outermost. CORS has to
    # wrap the request-context middleware so the 413 and 429 responses that
    # middleware writes itself still carry CORS headers; without them a
    # browser reports "network error" instead of the real status.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        # Authentication is a bearer token in a header, never a cookie, so
        # credentialed cross-origin requests are not needed.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )

    register_exception_handlers(app)
    app.include_router(v1_router, prefix="/v1")
    return app


app = create_app()
