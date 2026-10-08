"""Translate Azure SDK exceptions into safe, structured application errors."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from azure.core.exceptions import AzureError as SdkAzureError
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)

from app.core.errors import (
    AzureAuthenticationError,
    AzureError,
    AzureNotFoundError,
    AzurePermissionDeniedError,
    AzureQueryError,
    AzureThrottledError,
)
from app.core.logging import redact
from app.core.metrics import AZURE_CALLS, AZURE_FAILURES

logger = logging.getLogger(__name__)


def _safe_azure_message(exc: HttpResponseError) -> str:
    """Azure query errors (e.g. KQL syntax) are useful to users; keep them short and redacted."""
    message = getattr(getattr(exc, "error", None), "message", None) or str(exc.message or "")
    message = redact(message.splitlines()[0] if message else "")
    return message[:400] or AzureQueryError.message


@asynccontextmanager
async def azure_call(operation: str) -> AsyncIterator[None]:
    AZURE_CALLS.inc(operation)
    try:
        yield
    except ClientAuthenticationError as exc:
        AZURE_FAILURES.inc(operation)
        logger.error("azure_auth_failed", extra={"operation": operation, "error_type": type(exc).__name__})
        raise AzureAuthenticationError() from exc
    except ResourceNotFoundError as exc:
        AZURE_FAILURES.inc(operation)
        raise AzureNotFoundError() from exc
    except HttpResponseError as exc:
        AZURE_FAILURES.inc(operation)
        status = exc.status_code or 0
        logger.warning("azure_call_failed", extra={"operation": operation, "status_code": status})
        if status in (401, 403):
            raise AzurePermissionDeniedError() from exc
        if status == 404:
            raise AzureNotFoundError() from exc
        if status == 429:
            raise AzureThrottledError() from exc
        if status == 400 and "failed to find metric configuration" in str(exc.message or exc).lower():
            # Azure rejects metrics that don't apply to this resource's OS, tier or SKU.
            raise AzureQueryError(
                "This metric is not available for this resource (it depends on the OS, tier or SKU).",
                code="METRIC_NOT_SUPPORTED",
            ) from exc
        if status == 400:
            raise AzureQueryError(_safe_azure_message(exc)) from exc
        raise AzureError() from exc
    except (ServiceRequestError, ServiceResponseError) as exc:
        # Connection failures, resets and read timeouts.
        AZURE_FAILURES.inc(operation)
        logger.error("azure_unreachable", extra={"operation": operation, "error_type": type(exc).__name__})
        raise AzureError("Azure could not be reached. Please retry shortly.", code="AZURE_UNREACHABLE") from exc
    except SdkAzureError as exc:
        # Anything else the SDK raises must still surface as an application error, never a crash.
        AZURE_FAILURES.inc(operation)
        logger.error("azure_call_error", extra={"operation": operation, "error_type": type(exc).__name__})
        raise AzureError() from exc
