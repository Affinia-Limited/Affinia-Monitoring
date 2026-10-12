"""Scoped access: the projects, environments and resources the caller may see and act on.

The caller's role decides *what* they may do (``Permission``); their ``AccessScope`` decides
*where*. It is computed once per request from the member's grants (``UserAccessGrant``) and is
default-deny: an empty scope sees nothing.

* Super Admins and members with an "all projects" grant are **unrestricted**.
* Otherwise visibility is the union of fully granted projects, fully granted environments and
  individually granted resources. A resource grant counts only while the resource stays in the
  environment it was granted in.
* Unassigned resources (no project) are visible only when unrestricted.

Routers combine both: ``require(Permission.x)`` plus the scope helpers below. Objects outside the
scope are reported as not found, so their existence is not revealed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError


class ScopeRequiredError(PermissionDeniedError):
    code = "SCOPE_REQUIRED"
    message = "This needs access to all projects."


class AccessOutOfScopeError(PermissionDeniedError):
    code = "ACCESS_OUT_OF_SCOPE"
    message = "You can only grant access you have yourself."


@dataclass(frozen=True)
class AccessScope:
    unrestricted: bool = False
    #: Projects granted as a whole.
    full_project_ids: frozenset[uuid.UUID] = frozenset()
    #: Environments granted as a whole, outside fully granted projects.
    full_environment_ids: frozenset[uuid.UUID] = frozenset()
    #: Individually granted resources that are still in the environment they were granted in.
    resource_ids: frozenset[uuid.UUID] = frozenset()
    #: Every project / environment the caller can see something in.
    visible_project_ids: frozenset[uuid.UUID] = frozenset()
    visible_environment_ids: frozenset[uuid.UUID] = frozenset()
    #: Environment -> project, for every visible environment.
    environment_projects: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)

    @classmethod
    def everything(cls) -> AccessScope:
        return cls(unrestricted=True)

    @classmethod
    def nothing(cls) -> AccessScope:
        return cls()

    # ---- questions ---------------------------------------------------------------------

    def can_see_project(self, project_id: uuid.UUID | None) -> bool:
        if self.unrestricted:
            return True
        return project_id is not None and project_id in self.visible_project_ids

    def can_see_environment(self, environment_id: uuid.UUID | None) -> bool:
        if self.unrestricted:
            return True
        return environment_id is not None and environment_id in self.visible_environment_ids

    def has_full_project(self, project_id: uuid.UUID | None) -> bool:
        if self.unrestricted:
            return True
        return project_id is not None and project_id in self.full_project_ids

    def has_full_environment(self, environment_id: uuid.UUID | None) -> bool:
        if self.unrestricted:
            return True
        if environment_id is None:
            return False
        if environment_id in self.full_environment_ids:
            return True
        return self.environment_projects.get(environment_id) in self.full_project_ids

    def can_see_resource(self, resource: Any) -> bool:
        """``resource`` is a ``Resource`` (or anything with ``id``, ``project_id``, ``environment_id``)."""
        if self.unrestricted:
            return True
        if resource.project_id is None:
            return False
        return (
            resource.project_id in self.full_project_ids
            or (resource.environment_id is not None and resource.environment_id in self.full_environment_ids)
            or resource.id in self.resource_ids
        )

    def covers_scope(
        self,
        *,
        resource: Any | None = None,
        project_id: uuid.UUID | None = None,
        environment_id: uuid.UUID | None = None,
    ) -> bool:
        """Whether a whole configured scope (a rule, a coverage) lies inside the caller's access.

        A specific resource needs that resource; an environment needs the whole environment; a
        project needs the whole project; nothing at all (organisation-wide) needs unrestricted.
        """
        if self.unrestricted:
            return True
        if resource is not None:
            return self.can_see_resource(resource)
        if environment_id is not None:
            return self.has_full_environment(environment_id)
        if project_id is not None:
            return self.has_full_project(project_id)
        return False

    # ---- SQL filters -------------------------------------------------------------------

    def resource_filter(self) -> ColumnElement[bool]:
        """Condition on ``Resource`` rows the caller may see."""
        from app.models import Resource

        if self.unrestricted:
            return true()
        parts: list[ColumnElement[bool]] = []
        if self.full_project_ids:
            parts.append(Resource.project_id.in_(self.full_project_ids))
        if self.full_environment_ids:
            parts.append(Resource.environment_id.in_(self.full_environment_ids))
        if self.resource_ids:
            parts.append(Resource.id.in_(self.resource_ids))
        if not parts:
            return false()
        return and_(Resource.project_id.is_not(None), or_(*parts))

    def project_filter(self) -> ColumnElement[bool]:
        from app.models import Project

        if self.unrestricted:
            return true()
        return Project.id.in_(self.visible_project_ids) if self.visible_project_ids else false()

    def environment_filter(self) -> ColumnElement[bool]:
        from app.models import Environment

        if self.unrestricted:
            return true()
        return Environment.id.in_(self.visible_environment_ids) if self.visible_environment_ids else false()

    def require_unrestricted(self) -> None:
        if not self.unrestricted:
            raise ScopeRequiredError()


async def load_access_scope(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, *, super_admin: bool
) -> AccessScope:
    """The member's scope from their grants (deleted projects, environments and resources are ignored)."""
    if super_admin:
        return AccessScope.everything()
    from app.models import Environment, Project, Resource, UserAccessGrant

    grants = list(
        await db.scalars(
            select(UserAccessGrant).where(
                UserAccessGrant.organization_id == organization_id, UserAccessGrant.user_id == user_id
            )
        )
    )
    if any(g.project_id is None for g in grants):
        return AccessScope.everything()
    if not grants:
        return AccessScope.nothing()

    wanted_projects = {g.project_id for g in grants if g.project_id}
    live_projects = set(
        await db.scalars(
            select(Project.id).where(
                Project.id.in_(wanted_projects),
                Project.organization_id == organization_id,
                Project.deleted_at.is_(None),
            )
        )
    )
    full_projects = {g.project_id for g in grants if g.project_id in live_projects and g.environment_id is None}

    env_grants = [g for g in grants if g.environment_id and g.project_id in live_projects]
    env_rows = (
        {
            e.id: e.project_id
            for e in await db.scalars(
                select(Environment).where(
                    Environment.id.in_({g.environment_id for g in env_grants}),
                    Environment.organization_id == organization_id,
                    Environment.deleted_at.is_(None),
                )
            )
        }
        if env_grants
        else {}
    )
    # A grant is valid only while the environment still belongs to the granted project.
    valid_env_grants = [g for g in env_grants if env_rows.get(g.environment_id) == g.project_id]  # type: ignore[arg-type]
    full_envs = {
        g.environment_id
        for g in valid_env_grants
        if g.resource_id is None and g.project_id not in full_projects and g.environment_id is not None
    }

    resource_grants = [g for g in valid_env_grants if g.resource_id is not None]
    resource_ids: set[uuid.UUID] = set()
    resource_envs: dict[uuid.UUID, uuid.UUID] = {}
    if resource_grants:
        expected = {g.resource_id: g.environment_id for g in resource_grants}
        for rid, env_id, project_id in (
            await db.execute(
                select(Resource.id, Resource.environment_id, Resource.project_id).where(
                    Resource.id.in_(set(expected)),
                    Resource.organization_id == organization_id,
                    Resource.deleted_at.is_(None),
                )
            )
        ).all():
            # Only while the resource stays in the environment it was granted in.
            if env_id is not None and env_id == expected.get(rid) and project_id is not None:
                if project_id in full_projects or env_id in full_envs:
                    continue  # already covered by a broader grant
                resource_ids.add(rid)
                resource_envs[rid] = env_id

    # Visible environments: whole environments, environments of whole projects, and environments
    # that contain a granted resource.
    environment_projects: dict[uuid.UUID, uuid.UUID] = {}
    if full_projects:
        for env_id, project_id in (
            await db.execute(
                select(Environment.id, Environment.project_id).where(
                    Environment.project_id.in_(full_projects), Environment.deleted_at.is_(None)
                )
            )
        ).all():
            environment_projects[env_id] = project_id
    for env_id in full_envs:
        environment_projects[env_id] = env_rows[env_id]
    for env_id in resource_envs.values():
        environment_projects[env_id] = env_rows[env_id]

    visible_projects = set(full_projects) | set(environment_projects.values())
    return AccessScope(
        unrestricted=False,
        full_project_ids=frozenset(full_projects),
        full_environment_ids=frozenset(e for e in full_envs if e is not None),
        resource_ids=frozenset(resource_ids),
        visible_project_ids=frozenset(visible_projects),
        visible_environment_ids=frozenset(environment_projects),
        environment_projects=environment_projects,
    )


def ids(values: Iterable[Any]) -> set[uuid.UUID]:
    return {uuid.UUID(str(v)) for v in values if v}
