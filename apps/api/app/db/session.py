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

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _make_engine(url: str) -> AsyncEngine:
    kwargs: dict[str, object] = {"echo": False, "future": True}
    if url.startswith("sqlite"):
        # SQLite connection args to keep async in one thread; disables
        # thread-check that fights aiosqlite.
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = _make_engine(settings.database_url)
        _sessionmaker = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
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
