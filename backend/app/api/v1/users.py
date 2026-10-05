from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, case, func, or_, select

from app.api.deps import CurrentUser, DbSession, require
from app.core.permissions import ROLE_DESCRIPTIONS, Permission, Role, permissions_for
from app.models import AuditLog, User
from app.schemas.common import Page
from app.schemas.misc import (
    AuditOut,
    RoleKey,
    RoleOut,
    UserDetailOut,
    UserInvite,
    UserOut,
    UserStatusKey,
    UserUpdate,
)
from app.services import user_management

router = APIRouter(tags=["users"])

UserManager = Annotated[CurrentUser, Depends(require(Permission.manage_users))]
Auditor = Annotated[CurrentUser, Depends(require(Permission.view_audit))]


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(user: Annotated[CurrentUser, Depends(require(Permission.view_dashboards))]) -> list[RoleOut]:
    return [
        RoleOut(
            key=r.value,
            name=r.value.replace("_", " ").title(),
            description=ROLE_DESCRIPTIONS[r],
            permissions=sorted(p.value for p in permissions_for(r)),
        )
        for r in Role
    ]


_STATUS_ORDER = {"active": 0, "pending": 1, "suspended": 2, "deactivated": 3}


async def _with_creators(db: DbSession, users: list[User], schema: type[UserOut] = UserOut) -> list[UserOut]:
    creator_ids = {u.created_by_id for u in users if u.created_by_id}
    names: dict[uuid.UUID, str] = {}
    if creator_ids:
        for creator in await db.scalars(select(User).where(User.id.in_(creator_ids))):
            names[creator.id] = creator.display_name or creator.email or "Unknown"
    out = []
    for u in users:
        item = schema.model_validate(u)
        item.created_by_name = names.get(u.created_by_id) if u.created_by_id else None
        out.append(item)
    return out


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    db: DbSession,
    user: UserManager,
    q: Annotated[str | None, Query(max_length=200, description="Search name or email")] = None,
    role: Annotated[RoleKey | None, Query()] = None,
    status: Annotated[UserStatusKey | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[UserOut]:
    query = select(User).where(User.organization_id == user.organization_id, User.deleted_at.is_(None))
    if q and q.strip():
        term = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        query = query.where(
            or_(
                func.lower(User.display_name).like(term, escape="\\"),
                func.lower(User.email).like(term, escape="\\"),
            )
        )
    if role:
        query = query.where(User.role_key == role)
    if status:
        query = query.where(User.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    status_rank = case(_STATUS_ORDER, value=User.status, else_=9)
    rows = list(
        await db.scalars(
            query.order_by(status_rank, func.coalesce(func.lower(User.display_name), func.lower(User.email)), User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(items=await _with_creators(db, rows), total=int(total or 0), page=page, page_size=page_size)


@router.post("/users/invite", response_model=UserDetailOut, status_code=201)
async def invite_user(body: UserInvite, request: Request, db: DbSession, user: UserManager) -> UserOut:
    """Adds a user as a pending invitation. They are activated by their first matching Entra sign-in."""
    target = await user_management.invite(
        db, user, email=body.email, role=Role(body.role_key), display_name=body.display_name, request=request
    )
    await db.commit()
    return (await _with_creators(db, [target], UserDetailOut))[0]


@router.get("/users/{user_id}", response_model=UserDetailOut)
async def get_user(user_id: uuid.UUID, db: DbSession, user: UserManager) -> UserOut:
    target = await user_management.get_member(db, user, user_id)
    return (await _with_creators(db, [target], UserDetailOut))[0]


@router.patch("/users/{user_id}", response_model=UserDetailOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, request: Request, db: DbSession, user: UserManager
) -> UserOut:
    target = await user_management.get_member(db, user, user_id)
    if body.role_key is not None:
        await user_management.change_role(db, user, target, Role(body.role_key), request)
    if body.display_name is not None:
        await user_management.update_profile(db, user, target, body.display_name.strip(), request)
    await db.commit()
    return (await _with_creators(db, [target], UserDetailOut))[0]


async def _transition(user_id: uuid.UUID, action: str, request: Request, db: DbSession, user: CurrentUser) -> UserOut:
    target = await user_management.get_member(db, user, user_id)
    await user_management.change_status(db, user, target, action, request)
    await db.commit()
    return (await _with_creators(db, [target], UserDetailOut))[0]


@router.post("/users/{user_id}/suspend", response_model=UserDetailOut)
async def suspend_user(user_id: uuid.UUID, request: Request, db: DbSession, user: UserManager) -> UserOut:
    """Blocks access immediately; the next API request from the user is refused."""
    return await _transition(user_id, "suspend", request, db, user)


@router.post("/users/{user_id}/reactivate", response_model=UserDetailOut)
async def reactivate_user(user_id: uuid.UUID, request: Request, db: DbSession, user: UserManager) -> UserOut:
    return await _transition(user_id, "reactivate", request, db, user)


@router.post("/users/{user_id}/deactivate", response_model=UserDetailOut)
async def deactivate_user(user_id: uuid.UUID, request: Request, db: DbSession, user: UserManager) -> UserOut:
    """Removes access (or revokes a pending invitation). The user row and audit history are kept."""
    return await _transition(user_id, "deactivate", request, db, user)


@router.get("/users/{user_id}/audit", response_model=Page[AuditOut])
async def user_audit(
    user_id: uuid.UUID,
    db: DbSession,
    user: UserManager,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[AuditOut]:
    """Actions performed on this user and by this user."""
    target = await user_management.get_member(db, user, user_id)
    query = select(AuditLog).where(
        AuditLog.organization_id == user.organization_id,
        or_(
            and_(AuditLog.target_type == "user", AuditLog.target_id == str(target.id)),
            AuditLog.user_id == target.id,
        ),
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(
        await db.scalars(query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    )
    return Page(items=[AuditOut.model_validate(r) for r in rows], total=int(total or 0), page=page, page_size=page_size)


@router.get("/audit-logs", response_model=Page[AuditOut])
async def audit_logs(
    db: DbSession,
    user: Auditor,
    action: Annotated[str | None, Query(max_length=100)] = None,
    result: Annotated[str | None, Query(pattern=r"^(success|failure|denied)$")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[AuditOut]:
    query = select(AuditLog).where(AuditLog.organization_id == user.organization_id)
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    if result:
        query = query.where(AuditLog.result == result)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(
        await db.scalars(query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    )
    return Page(items=[AuditOut.model_validate(r) for r in rows], total=int(total or 0), page=page, page_size=page_size)
