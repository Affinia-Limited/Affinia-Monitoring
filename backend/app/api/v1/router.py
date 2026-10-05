from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    auth,
    azure_connections,
    dashboards,
    logs,
    overview,
    projects,
    resources,
    search,
    users,
)
from app.schemas.common import ErrorResponse

_ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
}

api_router = APIRouter(prefix="/api/v1", responses=_ERRORS)  # type: ignore[arg-type]
for module in (auth, overview, projects, azure_connections, resources, dashboards, logs, alerts, search, users):
    api_router.include_router(module.router)
