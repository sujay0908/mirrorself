"""Alembic environment configured for MirrorSelf async SQLAlchemy."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.database import Base
from app.models import user, conversation, fact  # noqa: F401  ensure tables register

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# NOTE: Do NOT use config.set_main_option() for the DATABASE_URL — it passes
# the value through Python's configparser which treats '%' as an interpolation
# marker and crashes on URL-encoded characters like '%40' (encoded '@').
# Instead, inject the URL directly in each migration path below.

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Pass DATABASE_URL directly — bypasses configparser interpolation issues.
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # Build config dict and explicitly inject the DATABASE_URL so that
    # config.set_main_option() override is actually seen by async_engine_from_config
    # (get_section() returns the raw ini dict, not the overridden value).
    cfg = dict(config.get_section(config.config_ini_section, {}))
    cfg["sqlalchemy.url"] = settings.DATABASE_URL

    # Supabase requires SSL on port 5432; asyncpg does not enable it automatically.
    connect_args: dict = {}
    if "supabase.co" in settings.DATABASE_URL:
        connect_args["ssl"] = "require"

    connectable = async_engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
