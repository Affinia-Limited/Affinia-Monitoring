"""Audit logging for administrative actions.

Details are sanitised: keys that look like credentials are dropped, and string
values are passed through the same redaction used for application logs.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import redact
from app.core.request_context import get_request_id
from app.models import AuditLog

if TYPE_CHECKING:
    from app.api.deps import CurrentUser

logger = logging.getLogger(__name__)

_BLOCKED_KEYS = ("token", "secret", "password", "authorization", "credential", "key", "cookie", "url")


def _sanitise(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, dict):
        return {
            str(k): _sanitise(v, depth + 1)
            for k, v in value.items()
            if not any(b in str(k).lower() for b in _BLOCKED_KEYS)
        }
    if isinstance(value, list):
        return [_sanitise(v, depth + 1) for v in value[:50]]
    if isinstance(value, str):
        return redact(value)[:500]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    from app.core.config import get_settings

    hops = get_settings().trusted_proxy_count
    forwarded = request.headers.get("x-forwarded-for")
    if hops and forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops][:64]
    return request.client.host if request.client else None


async def record_audit(
    db: AsyncSession,
    *,
    action: str,
    user: CurrentUser | None = None,
    organization_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    result: str = "success",
    request: Request | None = None,
    details: dict[str, Any] | None = None,
    actor: str | None = None,
) -> None:
    entry = AuditLog(
        organization_id=organization_id or (user.organization_id if user else None),
        user_id=user.id if user else None,
        actor=actor or (user.email or user.display_name or str(user.id) if user else "system"),
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:400] if request else None),
        request_id=get_request_id(),
        details=_sanitise(details or {}),
    )
    db.add(entry)
    logger.info("audit", extra={"action": action, "result": result, "target_type": target_type})
