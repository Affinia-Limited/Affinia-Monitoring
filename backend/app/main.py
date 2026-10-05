"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import TaskBackend, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.db.session import dispose_engine, session_scope
from app.services.azure.provider import close_azure_services
from app.services.discovery import mark_interrupted_runs
from app.services.monitors.registry import validate_all

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    validate_all()
    try:
        from app.services.dashboards.generator import sync_templates

        async with session_scope() as db:
            await sync_templates(db)
            if settings.task_backend is TaskBackend.inline:
                await mark_interrupted_runs(db)
    except Exception:
        # The schema may not be migrated yet; /ready will report the database state.
        logger.warning("template_sync_skipped")
    logger.info(
        "startup",
        extra={
            "environment": settings.environment.value,
            "auth_mode": settings.auth_mode.value,
            "azure_provider": settings.azure_provider.value,
        },
    )
    yield
    await close_azure_services()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    docs = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()
