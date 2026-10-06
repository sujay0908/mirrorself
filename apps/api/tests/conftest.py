"""Shared pytest fixtures.

The suite runs against an isolated per-test in-memory SQLite database and
overrides the auth + DB dependencies. No network. No real Supabase. No real
LLM provider — the MockProvider is used exclusively.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable

# Set test env BEFORE any app imports so `Settings()` is constructed with them.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("LLM_MODEL", "mock-echo")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import (
    db_session_dep,
    get_current_user,
    sessionmaker_dep,
)
from app.auth.models import AuthenticatedUser
from app.config import reset_settings_cache
from app.conversation import models as _conv_models  # noqa: F401
from app.db.base import Base
from app.goal import models as _goal_models  # noqa: F401
from app.llm.registry import reset_provider_cache
from app.main import create_app
from app.memory import models as _mem_models  # noqa: F401
from app.reflection import models as _refl_models  # noqa: F401

# Import ORM models so they are attached to Base.metadata.
from app.twin import models as _twin_models  # noqa: F401


@pytest.fixture
def user_a() -> AuthenticatedUser:
    return AuthenticatedUser(supabase_id=uuid.uuid4(), email="a@example.com")


@pytest.fixture
def user_b() -> AuthenticatedUser:
    return AuthenticatedUser(supabase_id=uuid.uuid4(), email="b@example.com")


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class _UserHolder:
    """Mutable current-user holder used by the get_current_user override."""

    def __init__(self, user: AuthenticatedUser) -> None:
        self.user = user


@pytest_asyncio.fixture
async def app_client(
    session_factory: async_sessionmaker[AsyncSession],
    user_a: AuthenticatedUser,
) -> AsyncIterator[tuple[FastAPI, AsyncClient, _UserHolder]]:
    reset_settings_cache()
    reset_provider_cache()

    app = create_app()
    holder = _UserHolder(user_a)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            try:
                yield s
            finally:
                await s.close()

    async def _override_user() -> AuthenticatedUser:
        return holder.user

    def _override_sessionmaker() -> async_sessionmaker[AsyncSession]:
        return session_factory

    app.dependency_overrides[db_session_dep] = _override_session
    app.dependency_overrides[sessionmaker_dep] = _override_sessionmaker
    app.dependency_overrides[get_current_user] = _override_user

    # raise_app_exceptions=False so unhandled exceptions in endpoints
    # exercise our registered Exception handler and come back as 5xx JSON
    # responses, instead of being re-raised to the test harness.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client, holder


@pytest.fixture
def as_user(app_client) -> Callable[[AuthenticatedUser], None]:
    """Return a setter that changes which user the current request is 'from'."""
    _app, _client, holder = app_client

    def _set(user: AuthenticatedUser) -> None:
        holder.user = user

    return _set


@pytest_asyncio.fixture
async def client(app_client) -> AsyncClient:
    _app, c, _holder = app_client
    return c
