"""Structured application errors.

Every error that leaves the API has the shape::

    {"error": {"code": "...", "message": "...", "request_id": "...", "details": {...}}}

Raw exception text is never returned to clients; unexpected exceptions are logged
server-side with the request id and surfaced as ``INTERNAL_ERROR``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = 400
    code: str = "BAD_REQUEST"
    message: str = "The request could not be processed."

    def __init__(self, message: str | None = None, *, code: str | None = None, details: dict[str, Any] | None = None):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"
    message = "Authentication is required."


class PermissionDeniedError(AppError):
    status_code = 403
    code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action."


class AccessNotGrantedError(AppError):
    """Authenticated by Entra ID, but not an active member of the platform.

    The message is deliberately generic: it never says whether an account, invitation
    or role exists. ``ACCESS_SUSPENDED`` is only ever returned to the suspended user.
    """

    status_code = 403
    code = "ACCESS_NOT_GRANTED"
    message = "Your account has been authenticated but has not been granted access to this application."


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "The requested item was not found."


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"
    message = "The request conflicts with the current state."


class ValidationFailedError(AppError):
    status_code = 422
    code = "VALIDATION_FAILED"
    message = "The request is invalid."


class RateLimitedError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests. Please retry shortly."


class AzureError(AppError):
    """Base class for failures talking to Azure. Messages are safe for display."""

    status_code = 502
    code = "AZURE_ERROR"
    message = "Azure returned an unexpected error."


class AzurePermissionDeniedError(AzureError):
    status_code = 403
    code = "AZURE_PERMISSION_DENIED"
    message = "The connected identity does not have permission to read this resource."


class AzureNotFoundError(AzureError):
    status_code = 404
    code = "AZURE_NOT_FOUND"
    message = "The Azure resource or subscription was not found."


class AzureThrottledError(AzureError):
    status_code = 503
    code = "AZURE_THROTTLED"
    message = "Azure is throttling requests. Please retry shortly."


class AzureAuthenticationError(AzureError):
    status_code = 502
    code = "AZURE_AUTHENTICATION_FAILED"
    message = "The platform could not authenticate to Azure. Check the managed identity configuration."


class AzureQueryError(AzureError):
    status_code = 400
    code = "AZURE_QUERY_ERROR"
    message = "Azure rejected the query."


def _error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": get_request_id()}
    if details:
        body["details"] = details
    return {"error": body}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        logger.log(level, "app_error", extra={"error_code": exc.code, "status_code": exc.status_code})
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only expose field locations and messages, never the submitted values.
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=_error_body("VALIDATION_FAILED", "The request is invalid.", {"errors": errors}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(codes.get(exc.status_code, "HTTP_ERROR"), message),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_body("INTERNAL_ERROR", "An unexpected error occurred. Quote the request id to support."),
        )
