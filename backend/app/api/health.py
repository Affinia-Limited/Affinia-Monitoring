"""Platform self-monitoring endpoints (not under /api/v1, unauthenticated, no sensitive data)."""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.metrics import render_prometheus
from app.db.session import get_engine

router = APIRouter(tags=["platform"])
_STARTED = time.time()


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness: the process is running."""
    return {"status": "ok"}


async def _checks() -> dict[str, dict[str, object]]:
    checks: dict[str, dict[str, object]] = {}
    start = time.perf_counter()
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
    except Exception:
        checks["database"] = {"status": "error"}
    if get_settings().redis_url:
        checks["redis"] = {"status": "ok" if await get_cache().ping() else "error"}
    return checks


@router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness: dependencies required to serve traffic are reachable."""
    checks = await _checks()
    healthy = all(c["status"] == "ok" for c in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503, content={"status": "ok" if healthy else "degraded", "checks": checks}
    )


@router.get("/health")
async def health() -> JSONResponse:
    checks = await _checks()
    healthy = all(c["status"] == "ok" for c in checks.values())
    settings = get_settings()
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "environment": settings.environment.value,
            "azure_provider": settings.azure_provider.value,
            "uptime_seconds": int(time.time() - _STARTED),
            "checks": checks,
        },
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus metrics. Restrict to the internal network at the ingress layer."""
    return render_prometheus()
