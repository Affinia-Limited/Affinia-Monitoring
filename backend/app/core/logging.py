"""Structured JSON logging with request correlation and secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from app.core.request_context import get_request_id, get_user_id

# Bearer tokens, JWTs and common secret-bearing query parameters.
_REDACTIONS = [
    (re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"), "Bearer [REDACTED]"),
    (re.compile(r"eyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]+"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)(client_secret|access_token|refresh_token|id_token|sig|code)=[^&\s]+"), r"\1=[REDACTED]"),
]

_SENSITIVE_KEYS = {"authorization", "access_token", "refresh_token", "id_token", "client_secret", "password", "token"}


def redact(value: str) -> str:
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.user_id = get_user_id()
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        for key in list(vars(record)):
            if key.lower() in _SENSITIVE_KEYS:
                setattr(record, key, "[REDACTED]")
        return True


class _Formatter(JsonFormatter):
    def add_fields(self, log_record: dict[str, Any], record: logging.LogRecord, message_dict: dict[str, Any]) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        if "exc_info" in log_record and isinstance(log_record["exc_info"], str):
            log_record["exc_info"] = redact(log_record["exc_info"])


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter("%(asctime)s %(message)s", timestamp=True))
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # The Azure SDK logs request headers at DEBUG; keep it quiet to avoid leaking anything.
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
