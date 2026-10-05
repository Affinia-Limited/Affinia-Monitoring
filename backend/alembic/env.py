"""Alembic environment. Uses DATABASE_URL from application settings (async engine)."""

from __future__ import annotations

import asyncio

from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  (registers all tables)
from alembic import context
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import init_engine

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # Shares engine construction with the app, including Entra token authentication.
    engine = init_engine(poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
