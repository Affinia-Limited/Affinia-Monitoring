"""Async engine and session management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str | None = None, **kwargs: object) -> AsyncEngine:
    global _engine, _sessionmaker
    settings = get_settings()
    db_url = url or settings.database_url
    options: dict[str, object] = {"echo": settings.database_echo, "pool_pre_ping": True}
    if db_url.startswith("postgresql") and "poolclass" not in kwargs:
        options.update(pool_size=10, max_overflow=20, pool_recycle=1800)
    options.update(kwargs)
    _engine = create_async_engine(db_url, **options)
    if settings.database_auth == "entra":
        _use_entra_token_auth(_engine)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


_POSTGRES_ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def _use_entra_token_auth(engine: AsyncEngine) -> None:
    """Use a Microsoft Entra access token as the PostgreSQL password for every new connection.

    Tokens last about an hour; ``pool_recycle`` (30 min) ensures connections are re-established with a
    fresh token. The credential caches tokens, so this does not call Entra on every connection.
    """
    from azure.identity import DefaultAzureCredential
    from sqlalchemy import event

    settings = get_settings()
    credential = DefaultAzureCredential(
        managed_identity_client_id=settings.azure_client_id,
        workload_identity_client_id=settings.azure_client_id,
        exclude_environment_credential=True,
        exclude_interactive_browser_credential=True,
    )

    @event.listens_for(engine.sync_engine, "do_connect")
    def _provide_token(dialect: object, conn_rec: object, cargs: object, cparams: dict[str, object]) -> None:
        cparams["password"] = credential.get_token(_POSTGRES_ENTRA_SCOPE).token


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session for background jobs: commits on success, rolls back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Handlers commit explicitly; anything uncommitted is rolled back."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
