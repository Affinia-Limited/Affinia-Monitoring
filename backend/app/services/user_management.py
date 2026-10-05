"""Administrator operations on platform members.

All rules are enforced here (not in the UI):

* nobody can change their own role or status;
* nobody can assign a role above their own, or manage someone ranked above them,
  so only a Super Admin can create, change or remove a Super Admin;
* the organisation always keeps at least one active Super Admin;
* access is removed by suspension or deactivation, never by deleting the row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import Role, role_rank
from app.models import Organization, User, UserStatus
from app.services.audit import record_audit
from app.services.authentication.users import count_active_super_admins, normalise_email

if TYPE_CHECKING:
    from app.api.deps import CurrentUser

#: How long an invitation can be redeemed by a first sign-in. Re-inviting refreshes it.
INVITATION_VALIDITY = timedelta(days=30)


async def get_member(db: AsyncSession, actor: CurrentUser, user_id: uuid.UUID) -> User:
    target = await db.scalar(
        select(User).where(User.id == user_id, User.organization_id == actor.organization_id, User.deleted_at.is_(None))
    )
    if target is None:
        raise NotFoundError("User not found.")
    return target


def _check_can_manage(actor: CurrentUser, target: User) -> None:
    if target.id == actor.id:
        raise ValidationFailedError("You cannot change your own role or status.", code="SELF_MODIFICATION")
    if role_rank(Role(target.role_key)) > role_rank(actor.role):
        raise PermissionDeniedError("You cannot manage a user with a higher role than your own.")


def _check_can_assign(actor: CurrentUser, role: Role) -> None:
    if role_rank(role) > role_rank(actor.role):
        raise PermissionDeniedError("You cannot assign a role higher than your own.")


async def _check_not_last_super_admin(db: AsyncSession, target: User) -> None:
    if target.role_key != Role.super_admin.value or target.status != UserStatus.active.value:
        return
    if await count_active_super_admins(db, target.organization_id, lock=True) <= 1:
        raise ConflictError("The platform must always have at least one active Super Admin.", code="LAST_SUPER_ADMIN")


async def invite(
    db: AsyncSession,
    actor: CurrentUser,
    *,
    email: str,
    role: Role,
    display_name: str | None,
    request: Request,
) -> User:
    _check_can_assign(actor, role)
    normalised = normalise_email(email)
    if normalised is None:
        raise ValidationFailedError("Enter the user's Microsoft Entra email address or UPN.")
    org = await db.get(Organization, actor.organization_id)
    if org is None or not org.entra_tenant_id:
        raise ValidationFailedError("This organisation is not linked to a Microsoft Entra tenant.")
    # Bound users keep the email from their token, which may differ in case.
    existing = await db.scalar(
        select(User).where(
            User.organization_id == actor.organization_id,
            func.lower(User.email) == normalised,
            User.deleted_at.is_(None),
        )
    )
    now = datetime.now(UTC)
    if existing is not None:
        if existing.status != UserStatus.pending.value:
            hint = " Reactivate it instead." if existing.status != UserStatus.active.value else ""
            raise ConflictError(f"A user with this email address already exists.{hint}", code="USER_EXISTS")
        _check_can_manage(actor, existing)
        existing.role_key = role.value
        existing.display_name = display_name or existing.display_name
        existing.invited_at, existing.invitation_expires_at = now, now + INVITATION_VALIDITY
        target, reinvite = existing, True
    else:
        target = User(
            organization_id=actor.organization_id,
            entra_tenant_id=org.entra_tenant_id,
            entra_object_id=None,
            email=normalised,
            display_name=display_name,
            role_key=role.value,
            status=UserStatus.pending.value,
            invited_at=now,
            invitation_expires_at=now + INVITATION_VALIDITY,
            created_by_id=actor.id,
        )
        db.add(target)
        reinvite = False
    await db.flush()
    await record_audit(
        db,
        action="user.invited",
        user=actor,
        target_type="user",
        target_id=str(target.id),
        request=request,
        details={"email": normalised, "role": role.value, "reinvite": reinvite},
    )
    return target


async def change_role(db: AsyncSession, actor: CurrentUser, target: User, role: Role, request: Request) -> User:
    if role.value == target.role_key:
        return target
    _check_can_manage(actor, target)
    _check_can_assign(actor, role)
    if target.role_managed_by_entra:
        raise ValidationFailedError(
            "This user's role is managed by Entra ID app-role assignments.", code="ROLE_MANAGED_BY_ENTRA"
        )
    await _check_not_last_super_admin(db, target)
    previous = target.role_key
    target.role_key = role.value
    await record_audit(
        db,
        action="user.role_changed",
        user=actor,
        target_type="user",
        target_id=str(target.id),
        request=request,
        details={"from": previous, "to": role.value},
    )
    return target


async def update_profile(
    db: AsyncSession, actor: CurrentUser, target: User, display_name: str, request: Request
) -> User:
    if target.id != actor.id:
        _check_can_manage(actor, target)
    if display_name != target.display_name:
        target.display_name = display_name
        await record_audit(
            db, action="user.updated", user=actor, target_type="user", target_id=str(target.id), request=request
        )
    return target


_TRANSITIONS: dict[str, tuple[set[str], str]] = {
    # action: (allowed current statuses, audit action)
    "suspend": ({UserStatus.active.value}, "user.suspended"),
    "reactivate": ({UserStatus.suspended.value, UserStatus.deactivated.value}, "user.reactivated"),
    "deactivate": (
        {UserStatus.pending.value, UserStatus.active.value, UserStatus.suspended.value},
        "user.deactivated",
    ),
}


async def change_status(db: AsyncSession, actor: CurrentUser, target: User, action: str, request: Request) -> User:
    allowed, audit_action = _TRANSITIONS[action]
    _check_can_manage(actor, target)
    if target.status not in allowed:
        raise ConflictError(f"A {target.status} user cannot be {audit_action.split('.')[1]}.", code="INVALID_STATUS")
    if action in ("suspend", "deactivate"):
        await _check_not_last_super_admin(db, target)
    previous = target.status
    now = datetime.now(UTC)
    if action == "suspend":
        target.status = UserStatus.suspended.value
    elif action == "deactivate":
        target.status = UserStatus.deactivated.value
        target.deactivated_at = now
        target.invitation_expires_at = None
    else:
        _check_can_assign(actor, Role(target.role_key))
        target.deactivated_at = None
        if target.entra_object_id is None:
            # A revoked invitation that was never redeemed becomes a fresh invitation.
            duplicate = await db.scalar(
                select(User.id).where(
                    User.organization_id == target.organization_id,
                    User.id != target.id,
                    func.lower(User.email) == (target.email or "").lower(),
                    User.status != UserStatus.deactivated.value,
                    User.deleted_at.is_(None),
                )
            )
            if duplicate is not None:
                raise ConflictError("Another user with this email address already exists.", code="USER_EXISTS")
            target.status = UserStatus.pending.value
            target.invited_at, target.invitation_expires_at = now, now + INVITATION_VALIDITY
        else:
            target.status = UserStatus.active.value
    await record_audit(
        db,
        action=audit_action,
        user=actor,
        target_type="user",
        target_id=str(target.id),
        request=request,
        details={"from": previous, "to": target.status},
    )
    return target
