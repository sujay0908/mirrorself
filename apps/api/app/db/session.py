"""Async engine + session factory.

The engine is lazy so tests can override `DATABASE_URL` before first use.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine_kwargs(url: str, settings: Settings) -> dict[str, object]:
    """Engine options for `url`. Split out so the pool policy is testable."""
    kwargs: dict[str, object] = {
        "echo": False,
        "future": True,
        # SQLAlchemy puts bound parameters into error messages and its own
        # logging. Those parameters are chat messages and memories, which must
        # never reach a log line.
        "hide_parameters": True,
    }
    if url.startswith("sqlite"):
        # SQLite connection args to keep async in one thread; disables
        # thread-check that fights aiosqlite.
        kwargs["connect_args"] = {"check_same_thread": False}
        return kwargs

    kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
        # A serverless database drops idle connections when it suspends. Without
        # a liveness check the first request after an idle period is handed a
        # dead connection and fails; with it, the pool reconnects transparently.
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.db_connect_timeout_seconds,
            "command_timeout": settings.db_command_timeout_seconds,
            "server_settings": {"application_name": "mirrorself-api"},
        },
    )
    return kwargs


def _make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, **engine_kwargs(url, get_settings()))


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = _make_engine(settings.database_url)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an AsyncSession, closes after request."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
        finally:
            await session.close()
