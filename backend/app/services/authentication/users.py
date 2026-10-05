"""Maps a validated Entra identity to a platform member.

Entra ID proves *who* the caller is. Whether they may use the platform is decided
here, from the ``users`` table:

1. Look up the user by the immutable identity ``(organization, tenant, oid)``.
2. Not found: the configured bootstrap Super Admin may be provisioned; otherwise a
   pending invitation for the same organisation, tenant and email is activated and
   the ``oid`` is bound to it permanently.
3. Anything else is denied with a generic ``ACCESS_NOT_GRANTED``.

Email is only used to match an *unbound* invitation. Once an ``oid`` is bound, the
email in later tokens is profile data and can never move access to another identity.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.core.config import AuthMode, get_settings
from app.core.errors import AccessNotGrantedError
from app.core.permissions import ENTRA_APP_ROLE_MAP, Role, highest_role
from app.core.security import TokenPrincipal
from app.models import Organization, User, UserStatus
from app.services.audit import record_audit

logger = logging.getLogger(__name__)

_LOGIN_TOUCH_INTERVAL = timedelta(minutes=5)
#: A denied identity is audited at most once per reason in this window (prevents audit flooding).
_DENIAL_AUDIT_INTERVAL_SECONDS = 600

SUSPENDED_MESSAGE = (
    "Your access to the Azure Monitoring Platform has been temporarily suspended. Please contact your administrator."
)


class DenialReason:
    user_not_found = "USER_NOT_FOUND"
    invitation_expired = "INVITATION_EXPIRED"
    identity_mismatch = "IDENTITY_MISMATCH"
    user_suspended = "USER_SUSPENDED"
    user_deactivated = "USER_DEACTIVATED"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:90] or "org"


def normalise_email(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value or None


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


async def find_organization(db: AsyncSession, tenant_id: str) -> Organization | None:
    return await db.scalar(
        select(Organization).where(Organization.entra_tenant_id == tenant_id, Organization.deleted_at.is_(None))
    )


async def get_or_create_organization(db: AsyncSession, tenant_id: str) -> Organization:
    org = await find_organization(db, tenant_id)
    if org is not None:
        return org
    # Only reached for the bootstrap identity or development mode, never for an arbitrary caller.
    org = Organization(name="Default organisation", slug=_slug(f"org-{tenant_id[:8]}"), entra_tenant_id=tenant_id)
    db.add(org)
    await db.flush()
    return org


async def count_active_super_admins(db: AsyncSession, organization_id: object, *, lock: bool = False) -> int:
    query = select(User.id).where(
        User.organization_id == organization_id,
        User.role_key == Role.super_admin.value,
        User.status == UserStatus.active.value,
        User.deleted_at.is_(None),
    )
    if lock:
        # Serialises concurrent demotions so two admins cannot remove the last Super Admin together.
        query = query.with_for_update()
    return len(list(await db.scalars(query)))


async def _find_by_identity(db: AsyncSession, org: Organization, principal: TokenPrincipal) -> User | None:
    return await db.scalar(
        select(User).where(
            User.organization_id == org.id,
            User.entra_tenant_id == principal.tenant_id,
            User.entra_object_id == principal.object_id,
            User.deleted_at.is_(None),
        )
    )


def _apply_profile(user: User, principal: TokenPrincipal) -> None:
    user.email = principal.email or user.email
    user.display_name = principal.display_name or user.display_name
    user.first_name = principal.first_name or user.first_name
    user.last_name = principal.last_name or user.last_name


def _apply_entra_roles(user: User, principal: TokenPrincipal) -> None:
    token_role = highest_role([ENTRA_APP_ROLE_MAP[r] for r in principal.app_roles if r in ENTRA_APP_ROLE_MAP])
    if token_role is not None:
        # Entra app-role assignments are authoritative for the role of an *approved* user.
        # They never grant membership on their own.
        user.role_key, user.role_managed_by_entra = token_role.value, True
    elif user.role_managed_by_entra:
        # App roles were removed in Entra: fall back to least privilege.
        user.role_key, user.role_managed_by_entra = Role.viewer.value, False


async def _deny(
    db: AsyncSession,
    principal: TokenPrincipal,
    org: Organization | None,
    reason: str,
    request: Request | None,
    user: User | None = None,
) -> AccessNotGrantedError:
    """Audits the denial (throttled) and returns the error to raise. The response never includes the reason."""
    cache_key = f"amp:denied:{principal.tenant_id}:{principal.object_id}:{reason}"
    if await get_cache().get(cache_key) is None:
        await get_cache().set(cache_key, 1, _DENIAL_AUDIT_INTERVAL_SECONDS)
        path = request.url.path if request else ""
        await record_audit(
            db,
            action="user.login_denied" if path.endswith(("/auth/session", "/auth/me")) else "user.access_denied",
            organization_id=org.id if org else None,
            actor=principal.email or principal.object_id,
            target_type="user",
            target_id=str(user.id) if user else None,
            result="denied",
            request=request,
            details={"reason": reason, "tenant_id": principal.tenant_id, "object_id": principal.object_id},
        )
        await db.commit()
    logger.info("access_not_granted", extra={"reason": reason})
    if reason == DenialReason.user_suspended:
        return AccessNotGrantedError(SUSPENDED_MESSAGE, code="ACCESS_SUSPENDED")
    return AccessNotGrantedError()


async def _bootstrap(
    db: AsyncSession, org: Organization, principal: TokenPrincipal, existing: User | None, request: Request | None
) -> User | None:
    """Provisions the configured first Super Admin. A no-op once the organisation has an active one."""
    settings = get_settings()
    if (principal.tenant_id.lower(), principal.object_id.lower()) not in settings.bootstrap_super_admins:
        return None
    if org.entra_tenant_id != principal.tenant_id or await count_active_super_admins(db, org.id) > 0:
        return None
    now = datetime.now(UTC)
    if existing is None:
        user = User(
            organization_id=org.id,
            entra_object_id=principal.object_id,
            entra_tenant_id=principal.tenant_id,
            role_key=Role.super_admin.value,
            status=UserStatus.active.value,
            activated_at=now,
        )
        _apply_profile(user, principal)
        db.add(user)
        await db.flush()
    elif existing.status == UserStatus.active.value:
        # An already-approved member listed for bootstrap is promoted; suspended or
        # deactivated accounts are never re-enabled by configuration.
        existing.role_key, existing.role_managed_by_entra = Role.super_admin.value, False
        user = existing
    else:
        return None
    await record_audit(
        db,
        action="user.bootstrapped",
        organization_id=org.id,
        actor="system",
        target_type="user",
        target_id=str(user.id),
        request=request,
        details={"role": Role.super_admin.value},
    )
    return user


async def _activate_invitation(
    db: AsyncSession, org: Organization, principal: TokenPrincipal, request: Request | None
) -> tuple[User | None, str]:
    """Binds the caller's ``oid`` to a matching pending invitation. Returns (user, denial reason if none)."""
    email = normalise_email(principal.email)
    if email is None:
        return None, DenialReason.user_not_found
    invitation = await db.scalar(
        select(User)
        .where(
            User.organization_id == org.id,
            User.entra_tenant_id == principal.tenant_id,
            User.status == UserStatus.pending.value,
            User.entra_object_id.is_(None),
            User.email == email,
            User.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if invitation is None:
        bound = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.organization_id == org.id, func.lower(User.email) == email, User.entra_object_id.is_not(None))
        )
        # Same email, different oid: never transfer access (renamed or recycled UPN).
        return None, DenialReason.identity_mismatch if bound else DenialReason.user_not_found
    expires = _aware(invitation.invitation_expires_at)
    now = datetime.now(UTC)
    if expires is not None and expires < now:
        return None, DenialReason.invitation_expired
    invitation.entra_object_id = principal.object_id
    invitation.status = UserStatus.active.value
    invitation.activated_at = now
    invitation.invitation_expires_at = None
    _apply_profile(invitation, principal)
    await db.flush()
    await record_audit(
        db,
        action="user.activated",
        organization_id=org.id,
        actor=principal.email or principal.object_id,
        target_type="user",
        target_id=str(invitation.id),
        request=request,
        details={"role": invitation.role_key},
    )
    return invitation, ""


async def _provision_dev_user(db: AsyncSession, principal: TokenPrincipal) -> tuple[User, bool]:
    org = await get_or_create_organization(db, principal.tenant_id)
    user = await _find_by_identity(db, org, principal)
    if user is None:
        user = User(
            organization_id=org.id,
            entra_object_id=principal.object_id,
            entra_tenant_id=principal.tenant_id,
            email=principal.email,
            display_name=principal.display_name,
            role_key=Role(get_settings().dev_user_role).value,
            status=UserStatus.active.value,
            activated_at=datetime.now(UTC),
        )
        db.add(user)
        await db.flush()
        return user, True
    return user, False


async def resolve_member(
    db: AsyncSession, principal: TokenPrincipal, request: Request | None = None
) -> tuple[User, bool]:
    """Returns (active user, is_new_session) or raises ``AccessNotGrantedError``. Commits are left to the caller."""
    if get_settings().auth_mode is AuthMode.dev:
        dev_user, created = await _provision_dev_user(db, principal)
        return dev_user, created or _touch(dev_user)

    org = await find_organization(db, principal.tenant_id)
    if org is None:
        if (principal.tenant_id.lower(), principal.object_id.lower()) in get_settings().bootstrap_super_admins:
            org = await get_or_create_organization(db, principal.tenant_id)
        else:
            raise await _deny(db, principal, None, DenialReason.user_not_found, request)

    user = await _find_by_identity(db, org, principal)
    bootstrapped = await _bootstrap(db, org, principal, user, request)
    is_new = False
    if bootstrapped is not None:
        user, is_new = bootstrapped, True
    elif user is None:
        invited, reason = await _activate_invitation(db, org, principal, request)
        if invited is None:
            raise await _deny(db, principal, org, reason, request)
        user, is_new = invited, True

    if user.status == UserStatus.suspended.value:
        raise await _deny(db, principal, org, DenialReason.user_suspended, request, user)
    if user.status != UserStatus.active.value:
        raise await _deny(db, principal, org, DenialReason.user_deactivated, request, user)

    _apply_profile(user, principal)
    _apply_entra_roles(user, principal)
    return user, _touch(user) or is_new


def _touch(user: User) -> bool:
    """Updates ``last_login_at`` at the start of a session (no activity for 5 minutes)."""
    now = datetime.now(UTC)
    last = _aware(user.last_login_at)
    if last is None or now - last > _LOGIN_TOUCH_INTERVAL:
        user.last_login_at = now
        return True
    return False
