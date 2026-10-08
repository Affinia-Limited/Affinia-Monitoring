"""Request dependencies: authentication, authorisation and rate limiting.

Every protected route depends on ``get_current_user`` (directly or through
``require(Permission.x)``), which checks, in order:

1. a valid Entra access token (``get_principal``),
2. membership: an approved user for that tenant and ``oid`` (``resolve_member``),
3. status ``active`` (pending, suspended and deactivated users are refused),
4. the route's permissions (``require``).

The frontend may hide controls based on ``/auth/me`` but is never trusted.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.core.config import AuthMode, get_settings
from app.core.errors import AccessNotGrantedError, AuthenticationError, PermissionDeniedError, RateLimitedError
from app.core.permissions import Permission, Role, permissions_for
from app.core.request_context import set_user_id
from app.core.security import EntraTokenValidator, TokenPrincipal
from app.db.session import get_db
from app.services.audit import client_ip, record_audit
from app.services.authentication.users import resolve_member
from app.services.azure.provider import get_azure_services
from app.services.azure.types import AzureServices

DbSession = Annotated[AsyncSession, Depends(get_db)]
Azure = Annotated[AzureServices, Depends(get_azure_services)]

DEV_PRINCIPAL = TokenPrincipal(
    object_id="00000000-0000-4000-8000-00000000dev1",
    tenant_id="00000000-0000-4000-8000-00000000dev0",
    email="developer@localhost",
    display_name="Local developer (dev auth)",
)

_validator: EntraTokenValidator | None = None


def get_validator() -> EntraTokenValidator:
    global _validator
    if _validator is None:
        _validator = EntraTokenValidator(get_settings())
    return _validator


def set_validator(validator: EntraTokenValidator | None) -> None:
    global _validator
    _validator = validator


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    organization_id: uuid.UUID
    email: str | None
    display_name: str | None
    role: Role
    permissions: frozenset[Permission]
    role_managed_by_entra: bool

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


async def _rate_limit(key: str, limit: int) -> None:
    window = int(time.time() // 60)
    count = await get_cache().incr(f"amp:rl:{key}:{window}", 70)
    if count > limit:
        raise RateLimitedError()


async def _record_auth_failure(key: str) -> None:
    """Count a failed authentication or access denial; over budget, answer 429 instead of 401/403.

    Only failures are counted and a valid token is never checked against the budget, so nobody
    (including an anonymous client sharing the same proxy IP) can lock legitimate users out.
    """
    count = await get_cache().incr(f"amp:rl:authfail:{key}:{int(time.time() // 60)}", 70)
    if count > get_settings().rate_limit_auth_failures_per_minute:
        raise RateLimitedError()


async def get_principal(request: Request) -> TokenPrincipal:
    settings = get_settings()
    if settings.auth_mode is AuthMode.dev:
        return DEV_PRINCIPAL
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    try:
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError()
        return await get_validator().validate(token.strip())
    except (AuthenticationError, PermissionDeniedError):
        await _record_auth_failure(f"ip:{client_ip(request) or 'unknown'}")
        raise


async def get_current_user(
    request: Request, db: DbSession, principal: Annotated[TokenPrincipal, Depends(get_principal)]
) -> CurrentUser:
    """The authenticated, approved and *active* caller. Raises ``ACCESS_NOT_GRANTED`` otherwise."""
    settings = get_settings()
    try:
        user, is_new_session = await resolve_member(db, principal, request)
    except AccessNotGrantedError:
        # A genuine identity without access: budget it per identity, not per (possibly shared) IP.
        await _record_auth_failure(f"principal:{principal.tenant_id}:{principal.object_id}")
        raise
    if settings.auth_mode is AuthMode.dev:
        user.role_key = Role(settings.dev_user_role).value
    role = Role(user.role_key)
    current = CurrentUser(
        id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        display_name=user.display_name,
        role=role,
        permissions=permissions_for(role),
        role_managed_by_entra=user.role_managed_by_entra,
    )
    # Interactive sign-ins are audited by POST /auth/session; this covers resumed sessions.
    if is_new_session and not request.url.path.endswith("/auth/session"):
        await record_audit(
            db,
            action="user.login_allowed",
            user=current,
            target_type="user",
            target_id=str(user.id),
            request=request,
            details={"trigger": "session_resumed"},
        )
    await db.commit()
    set_user_id(str(user.id))
    await _rate_limit(f"user:{user.id}", settings.rate_limit_per_minute)
    return current


def require(*permissions: Permission) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    async def _dependency(
        request: Request, db: DbSession, user: Annotated[CurrentUser, Depends(get_current_user)]
    ) -> CurrentUser:
        missing = [p for p in permissions if not user.has(p)]
        if missing:
            await record_audit(
                db,
                action="authorization.denied",
                user=user,
                result="denied",
                request=request,
                details={"path": request.url.path, "method": request.method, "required": [p.value for p in missing]},
            )
            await db.commit()
            raise PermissionDeniedError()
        return user

    return _dependency


async def enforce_kql_rate_limit(user: CurrentUser) -> None:
    await _rate_limit(f"kql:{user.id}", get_settings().rate_limit_kql_per_minute)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
