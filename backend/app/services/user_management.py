"""Administrator operations on platform members.

All rules are enforced here (not in the UI):

* nobody can change their own role or status;
* nobody can assign a role above their own, or manage someone ranked above them,
  so only a Super Admin can create, change or remove a Super Admin;
* a manager sees and manages only members whose access (projects, environments, resources)
  lies inside their own, and can only grant access they have themselves;
* the organisation always keeps at least one active Super Admin;
* access is removed by suspension or deactivation; a deactivated (revoked) user can then be
  deleted: their personal data is erased and the row is kept, so the audit history stays intact.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import Role, role_rank
from app.models import AuditLog, Organization, User, UserAccessGrant, UserStatus
from app.schemas.misc import AccessGrantIn
from app.services.access_grants import GrantKey, can_manage_access, replace_grants, validate_grants
from app.services.audit import record_audit
from app.services.authentication.users import count_active_super_admins, normalise_email
from app.services.email import mask_email

if TYPE_CHECKING:
    from app.api.deps import CurrentUser

#: How long an invitation can be redeemed by a first sign-in. Re-inviting refreshes it.
INVITATION_VALIDITY = timedelta(days=30)


async def get_member(db: AsyncSession, actor: CurrentUser, user_id: uuid.UUID) -> User:
    target = await db.scalar(
        select(User).where(User.id == user_id, User.organization_id == actor.organization_id, User.deleted_at.is_(None))
    )
    if target is None or not await can_see_member(db, actor, target):
        raise NotFoundError("User not found.")
    return target


async def can_see_member(db: AsyncSession, actor: CurrentUser, target: User) -> bool:
    """Members ranked above the manager, or with access outside the manager's, are not visible."""
    if target.id == actor.id:
        return True
    if role_rank(Role(target.role_key)) > role_rank(actor.role):
        return False
    return await can_manage_access(db, actor.access, target)


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
    grants: list[AccessGrantIn] | None = None,
) -> User:
    _check_can_assign(actor, role)
    keys: list[GrantKey]
    described: list[dict[str, str | None]]
    if role is Role.super_admin:
        keys, described = [], [{"scope": "unrestricted (Super Admin)"}]
    else:
        if not grants:
            raise ValidationFailedError(
                "Choose what the user can access: all projects, or specific projects, environments or resources.",
                code="ACCESS_REQUIRED",
            )
        keys, described = await validate_grants(db, actor, grants)
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
        # Someone outside the inviter's access: one generic answer, nothing about their status or rank.
        if not await can_see_member(db, actor, existing):
            raise ConflictError("A user with this email address already exists.", code="USER_EXISTS")
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
    await replace_grants(db, actor, target, keys)
    await record_audit(
        db,
        action="user.invited",
        user=actor,
        target_type="user",
        target_id=str(target.id),
        request=request,
        details={"email": normalised, "role": role.value, "reinvite": reinvite, "access": described},
    )
    return target


async def set_access(
    db: AsyncSession, actor: CurrentUser, target: User, grants: list[AccessGrantIn], request: Request
) -> User:
    """Replaces a member's access. Super Admins are always unrestricted and have no grants."""
    if target.id == actor.id:
        raise ValidationFailedError("You cannot change your own access.", code="SELF_MODIFICATION")
    _check_can_manage(actor, target)
    if target.role_key == Role.super_admin.value:
        raise ValidationFailedError(
            "Super Admins always have access to everything; change the role to limit their access.",
            code="SUPER_ADMIN_UNRESTRICTED",
        )
    keys, described = await validate_grants(db, actor, grants) if grants else ([], [])
    await replace_grants(db, actor, target, keys)
    await record_audit(
        db,
        action="user.access_changed",
        user=actor,
        target_type="user",
        target_id=str(target.id),
        request=request,
        details={"access": described or [{"scope": "none"}]},
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


#: Shown wherever a deleted user is referenced (e.g. "Invited by").
DELETED_USER_NAME = "Deleted user"


async def delete_user(db: AsyncSession, actor: CurrentUser, target: User, request: Request) -> None:
    """Delete a revoked user: erase their personal data and access, keep the audit history.

    Only deactivated users (including revoked invitations) can be deleted, so an active account is
    never removed by accident. The row is soft-deleted rather than dropped: audit entries keep
    pointing at it and read "Deleted user". If the same Microsoft account signs in again it is
    unknown (access is refused), and the email address can be invited again as a new user.
    """
    if target.id == actor.id:
        raise ValidationFailedError("You cannot delete your own account.")
    _check_can_manage(actor, target)
    if target.status != UserStatus.deactivated.value:
        raise ConflictError("Revoke this user's access before deleting them.", code="USER_NOT_REVOKED")
    masked = mask_email(target.email) if target.email else None
    pseudonym = f"deleted-user-{str(target.id)[:8]}"
    await record_audit(
        db,
        action="user.deleted",
        user=actor,
        target_type="user",
        target_id=str(target.id),
        request=request,
        details={"email": masked, "role": target.role_key},
    )
    # Data minimisation: erase identifying data, here and in the audit trail, keep the events.
    await db.execute(update(AuditLog).where(AuditLog.user_id == target.id).values(actor=pseudonym))
    entries = await db.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == target.organization_id,
            AuditLog.target_type == "user",
            AuditLog.target_id == str(target.id),
        )
    )
    for entry in entries:
        if isinstance(entry.details, dict) and entry.details.get("email") and entry.details["email"] != masked:
            entry.details = {**entry.details, "email": masked}
    for grant in await db.scalars(select(UserAccessGrant).where(UserAccessGrant.user_id == target.id)):
        await db.delete(grant)
    target.email = None
    target.display_name = DELETED_USER_NAME
    target.first_name = None
    target.last_name = None
    target.entra_object_id = None
    target.invitation_expires_at = None
    target.deleted_at = datetime.now(UTC)
