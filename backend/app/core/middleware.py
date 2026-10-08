"""HTTP middleware: request ids, structured access logs, latency metrics and security headers."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.core.request_context import set_request_id, set_user_id

logger = logging.getLogger("app.access")
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_UUID_SEGMENT = re.compile(r"/[0-9a-fA-F-]{36}(?=/|$)")

_DOCS_PATHS = ("/api/docs", "/api/redoc", "/api/openapi.json")


def _route_template(request: Request) -> str:
    """The matched route with its parameters named, e.g. ``/api/v1/resources/{resource_id}``.

    Never the raw path: arbitrary URLs must not create new metric series. Unmatched requests share
    one label. (Nested routers only expose their own part of the template, so the parameters are
    put back into the real path instead.)
    """
    if request.scope.get("route") is None:
        return "unmatched"
    params = {str(v): k for k, v in (request.scope.get("path_params") or {}).items()}
    return "/".join(f"{{{params[seg]}}}" if seg in params else seg for seg in request.url.path.split("/"))


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        set_request_id(request_id)
        set_user_id(None)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            elapsed = time.perf_counter() - start
            route = _UUID_SEGMENT.sub("/{id}", request.url.path)
            HTTP_REQUESTS.inc(f"{status // 100}xx")
            HTTP_LATENCY.observe(_route_template(request), elapsed)
            if request.url.path not in ("/live", "/ready", "/metrics"):
                logger.info(
                    "http_request",
                    extra={
                        "method": request.method,
                        "route": route,
                        "status_code": status,
                        "duration_ms": round(elapsed * 1000, 1),
                    },
                )
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        settings = get_settings()
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith(_DOCS_PATHS):
            # Swagger UI needs its CDN assets; docs are disabled in production.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
                "https://fastapi.tiangolo.com; frame-ancestors 'none'",
            )
        else:
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.environment.value not in ("development", "test"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response
