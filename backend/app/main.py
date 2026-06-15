"""
MirrorSelf FastAPI application entrypoint.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, chat, me, onboarding, public
from app.core.config import settings
from app.core.database import Base, engine
from app.core.logging import logger
from app.core.redis_client import redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Test redis
    try:
        await redis_client.client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis ping failed at startup: {e}")
    yield
    # Shutdown
    await engine.dispose()
    await redis_client.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="A digital twin platform: face + voice + personality + memory + AI.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


@app.get("/health/ready")
async def ready() -> JSONResponse:
    """Readiness probe: checks Postgres + Redis."""
    pg_ok = True
    redis_ok = True
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
    except Exception as e:
        logger.error(f"Postgres check failed: {e}")
        pg_ok = False
    try:
        await redis_client.client.ping()
    except Exception:
        redis_ok = False
    code = 200 if (pg_ok and redis_ok) else 503
    return JSONResponse(
        status_code=code,
        content={"postgres": pg_ok, "redis": redis_ok},
    )


# Mount routers
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(me.router, prefix=settings.API_V1_PREFIX)
app.include_router(onboarding.router, prefix=settings.API_V1_PREFIX)
app.include_router(chat.router, prefix=settings.API_V1_PREFIX)
app.include_router(public.router, prefix=settings.API_V1_PREFIX)
