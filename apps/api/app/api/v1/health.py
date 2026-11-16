"""System endpoints.

`/v1/health` is liveness: the process is up and serving. It touches nothing
else, so a database outage does not make the platform restart a healthy
process.

`/v1/ready` is readiness: the process can do real work right now. It runs a
trivial query with a short deadline and reports which optional capabilities
are configured.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.api.deps import SessionmakerDep
from app.config import get_settings
from app.llm.registry import ProviderNotConfiguredError, get_llm_provider
from app.observability.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

_READY_DB_DEADLINE_SECONDS = 5.0


@router.get("/health", summary="Liveness")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness")
async def ready(sessionmaker: SessionmakerDep) -> JSONResponse:
    started = time.perf_counter()
    database = "ok"
    try:
        async with asyncio.timeout(_READY_DB_DEADLINE_SECONDS):
            async with sessionmaker() as session:
                await session.execute(text("SELECT 1"))
    except Exception as exc:
        database = "unavailable"
        logger.error("ready.database_unavailable", error_type=type(exc).__name__)
    db_ms = int((time.perf_counter() - started) * 1000)

    try:
        get_llm_provider()
        llm = "configured"
    except ProviderNotConfiguredError:
        # Not a readiness failure: every non-AI surface works without it.
        llm = "not_configured"
    except Exception:
        llm = "error"

    ok = database == "ok"
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "degraded",
            "checks": {"database": database, "llm": llm},
            "database_latency_ms": db_ms,
        },
    )


@router.get("/system/version", summary="Build info")
async def version() -> dict[str, str | None]:
    settings = get_settings()
    return {
        "api": "v1",
        "version": __version__,
        "env": settings.app_env,
        "commit": settings.git_commit,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
    }
