"""Members' access grants: views, validation against the granter's own access, and management rules.

A manager can only give access they have themselves, and can only see or manage members whose
access lies entirely inside theirs (see ``can_manage_access``). Everything is enforced here, not
in the UI.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessOutOfScopeError, AccessScope
from app.core.errors import ValidationFailedError
from app.core.permissions import Role
from app.models import Environment, Project, Resource, User, UserAccessGrant
from app.schemas.misc import AccessGrantIn, AccessGrantOut, UserAccessOut

if TYPE_CHECKING:
    from app.api.deps import CurrentUser


@dataclass(frozen=True)
class GrantKey:
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None

    @property
    def all_projects(self) -> bool:
        return self.project_id is None


ALL_PROJECTS = GrantKey(None)


async def grants_by_user(
    db: AsyncSession, organization_id: uuid.UUID, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[UserAccessGrant]]:
    out: dict[uuid.UUID, list[UserAccessGrant]] = {uid: [] for uid in user_ids}
    if not user_ids:
        return out
    for g in await db.scalars(
        select(UserAccessGrant)
        .where(UserAccessGrant.organization_id == organization_id, UserAccessGrant.user_id.in_(user_ids))
        .order_by(UserAccessGrant.created_at, UserAccessGrant.id)
    ):
        out.setdefault(g.user_id, []).append(g)
    return out


async def access_views(
    db: AsyncSession, users: Sequence[User], grants: dict[uuid.UUID, list[UserAccessGrant]]
) -> dict[uuid.UUID, UserAccessOut]:
    """``UserAccessOut`` per user, with project / environment / resource names."""
    every = [g for u in users for g in grants.get(u.id, [])]
    project_ids = {g.project_id for g in every if g.project_id}
    env_ids = {g.environment_id for g in every if g.environment_id}
    resource_ids = {g.resource_id for g in every if g.resource_id}
    projects = (
        {p.id: p.name for p in await db.scalars(select(Project).where(Project.id.in_(project_ids)))}
        if project_ids
        else {}
    )
    envs = (
        {e.id: e.name for e in await db.scalars(select(Environment).where(Environment.id.in_(env_ids)))}
        if env_ids
        else {}
    )
    resources = (
        {r.id: r.name for r in await db.scalars(select(Resource).where(Resource.id.in_(resource_ids)))}
        if resource_ids
        else {}
    )
    out: dict[uuid.UUID, UserAccessOut] = {}
    for u in users:
        mine = grants.get(u.id, [])
        unrestricted = u.role_key == Role.super_admin.value or any(g.project_id is None for g in mine)
        out[u.id] = UserAccessOut(
            unrestricted=unrestricted,
            grants=[]
            if u.role_key == Role.super_admin.value
            else [
                AccessGrantOut(
                    id=g.id,
                    project_id=g.project_id,
                    project_name=projects.get(g.project_id) if g.project_id else None,
                    environment_id=g.environment_id,
                    environment_name=envs.get(g.environment_id) if g.environment_id else None,
                    resource_id=g.resource_id,
                    resource_name=resources.get(g.resource_id) if g.resource_id else None,
                )
                for g in mine
            ],
        )
    return out


async def scope_for_user(db: AsyncSession, user: User) -> AccessScope:
    from app.core.access import load_access_scope

    return await load_access_scope(
        db, user.organization_id, user.id, super_admin=user.role_key == Role.super_admin.value
    )


async def can_manage_access(db: AsyncSession, manager: AccessScope, target: User) -> bool:
    """A manager sees and manages a member only if the member's access lies inside the manager's.

    Super Admins are unrestricted, so only unrestricted managers qualify (the role rank rule then
    limits them to Super Admins). A member without grants is inside anyone's access.
    """
    if manager.unrestricted:
        return True
    if target.role_key == Role.super_admin.value:
        return False
    grants = list(
        await db.scalars(
            select(UserAccessGrant).where(
                UserAccessGrant.organization_id == target.organization_id, UserAccessGrant.user_id == target.id
            )
        )
    )
    for g in grants:
        if g.project_id is None:
            return False
        if g.environment_id is None:
            if not manager.has_full_project(g.project_id):
                return False
        elif g.resource_id is None:
            if not manager.has_full_environment(g.environment_id):
                return False
        else:
            resource = await db.get(Resource, g.resource_id)
            # A grant for a resource that has moved or gone grants nothing; judge it by its environment.
            if resource is not None and resource.environment_id == g.environment_id:
                if not manager.can_see_resource(resource):
                    return False
            elif not manager.has_full_environment(g.environment_id):
                return False
    return True


async def validate_grants(
    db: AsyncSession, actor: CurrentUser, requested: Sequence[AccessGrantIn]
) -> tuple[list[GrantKey], list[dict[str, str | None]]]:
    """Checks every requested grant (hierarchy, organisation, the actor's own access) and returns the
    normalised set plus a named description for the audit log.

    Normalised: "all projects" alone if present; grants already covered by a broader one dropped;
    duplicates removed. Unknown or invisible ids are reported as not found.
    """
    scope = actor.access
    org = actor.organization_id
    keys: list[GrantKey] = []
    for item in requested:
        if item.project_id is None:
            if item.environment_id or item.resource_id:
                raise ValidationFailedError("Choose the project of the environment.")
            if not scope.unrestricted:
                raise AccessOutOfScopeError("Only users with access to all projects can grant all projects.")
            keys.append(ALL_PROJECTS)
            continue
        if item.resource_id and not item.environment_id:
            raise ValidationFailedError("Choose the environment of the resource.")
        keys.append(GrantKey(item.project_id, item.environment_id, item.resource_id))

    if ALL_PROJECTS in keys:
        return [ALL_PROJECTS], [{"scope": "all projects"}]

    project_ids = {k.project_id for k in keys}
    env_ids = {k.environment_id for k in keys if k.environment_id}
    resource_ids = {k.resource_id for k in keys if k.resource_id}
    projects = {
        p.id: p
        for p in await db.scalars(
            select(Project).where(
                Project.id.in_(project_ids), Project.organization_id == org, Project.deleted_at.is_(None)
            )
        )
    }
    envs = (
        {
            e.id: e
            for e in await db.scalars(
                select(Environment).where(
                    Environment.id.in_(env_ids), Environment.organization_id == org, Environment.deleted_at.is_(None)
                )
            )
        }
        if env_ids
        else {}
    )
    resources = (
        {
            r.id: r
            for r in await db.scalars(
                select(Resource).where(
                    Resource.id.in_(resource_ids), Resource.organization_id == org, Resource.deleted_at.is_(None)
                )
            )
        }
        if resource_ids
        else {}
    )
    for k in keys:
        project = projects.get(k.project_id) if k.project_id else None
        if project is None or not scope.can_see_project(project.id):
            raise ValidationFailedError("Project not found.")
        if k.environment_id is None:
            if not scope.has_full_project(project.id):
                raise AccessOutOfScopeError(f"You cannot grant the whole project '{project.name}'.")
            continue
        env = envs.get(k.environment_id)
        if env is None or env.project_id != project.id or not scope.can_see_environment(env.id):
            raise ValidationFailedError("Environment not found in that project.")
        if k.resource_id is None:
            if not scope.has_full_environment(env.id):
                raise AccessOutOfScopeError(f"You cannot grant the whole environment '{project.name} / {env.name}'.")
            continue
        resource = resources.get(k.resource_id)
        if (
            resource is None
            or resource.environment_id != env.id
            or resource.project_id != project.id
            or not scope.can_see_resource(resource)
        ):
            raise ValidationFailedError("Resource not found in that environment.")

    full_projects = {k.project_id for k in keys if k.environment_id is None}
    full_envs = {k.environment_id for k in keys if k.environment_id and k.resource_id is None}
    normalised: list[GrantKey] = []
    for k in keys:
        if k in normalised:
            continue
        if k.environment_id is not None and k.project_id in full_projects:
            continue
        if k.resource_id is not None and k.environment_id in full_envs:
            continue
        normalised.append(k)

    described: list[dict[str, str | None]] = []
    for k in normalised:
        env = envs.get(k.environment_id) if k.environment_id else None
        res = resources.get(k.resource_id) if k.resource_id else None
        described.append(
            {
                "project": projects[k.project_id].name if k.project_id else None,
                "environment": env.name if env else None,
                "resource": res.name if res else None,
            }
        )
    return normalised, described


async def replace_grants(db: AsyncSession, actor: CurrentUser, target: User, keys: Sequence[GrantKey]) -> None:
    await db.execute(
        delete(UserAccessGrant).where(
            UserAccessGrant.organization_id == target.organization_id, UserAccessGrant.user_id == target.id
        )
    )
    for k in keys:
        db.add(
            UserAccessGrant(
                organization_id=target.organization_id,
                user_id=target.id,
                project_id=k.project_id,
                environment_id=k.environment_id,
                resource_id=k.resource_id,
                created_by_id=actor.id,
            )
        )
    await db.flush()
