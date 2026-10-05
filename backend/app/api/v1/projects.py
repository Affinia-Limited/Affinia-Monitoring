from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import Azure, CurrentUser, DbSession, require
from app.api.v1.common import TimeRangeDep
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.permissions import Permission
from app.models import Environment, Project, Resource
from app.schemas.misc import ComparisonOut
from app.schemas.projects import (
    EnvironmentIn,
    EnvironmentOut,
    EnvironmentSummary,
    EnvironmentUpdate,
    ProjectIn,
    ProjectOut,
    ProjectUpdate,
)
from app.services.audit import record_audit
from app.services.comparison import compare_environments
from app.services.discovery import reassign_resources
from app.services.views import (
    ScopeHealth,
    active_alert_counts_by_environment,
    active_alert_counts_by_project,
    health_by_scope,
)

router = APIRouter(prefix="/projects", tags=["projects"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_resources))]
Manager = Annotated[CurrentUser, Depends(require(Permission.manage_projects))]


async def _get_project(db: DbSession, user: CurrentUser, project_id: uuid.UUID) -> Project:
    project = await db.scalar(
        select(Project)
        .where(Project.id == project_id, Project.organization_id == user.organization_id, Project.deleted_at.is_(None))
        .options(selectinload(Project.environments))
    )
    if project is None:
        raise NotFoundError("Project not found.")
    return project


async def _project_views(db: DbSession, user: CurrentUser, projects: list[Project]) -> list[ProjectOut]:
    """Projects with health of their *monitored* resources (inventory items carry no health signal)."""
    scopes = await health_by_scope(db, user.organization_id, [p.id for p in projects])
    alerts = await active_alert_counts_by_project(db, user.organization_id)
    env_alerts = await active_alert_counts_by_environment(db, user.organization_id)
    views = []
    for project in projects:
        out = ProjectOut.model_validate(project, from_attributes=True)
        envs = []
        for env in project.environments:
            scope = scopes.get((project.id, env.id), ScopeHealth())
            summary = EnvironmentSummary.model_validate(env, from_attributes=True)
            summary.health = scope.counts
            summary.status = scope.status
            summary.active_alerts = env_alerts.get((project.id, env.id), 0)
            summary.last_checked_at = scope.last_checked_at
            envs.append(summary)
        project_scope = scopes.get((project.id, None), ScopeHealth())
        out.environments = envs
        out.health = project_scope.counts
        out.status = project_scope.status
        out.active_alerts = alerts.get(project.id, 0)
        out.last_checked_at = project_scope.last_checked_at
        views.append(out)
    return views


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: DbSession, user: Viewer) -> list[ProjectOut]:
    projects = list(
        await db.scalars(
            select(Project)
            .where(Project.organization_id == user.organization_id, Project.deleted_at.is_(None))
            .options(selectinload(Project.environments))
            .order_by(Project.name)
        )
    )
    return await _project_views(db, user, projects)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, request: Request, db: DbSession, user: Manager) -> ProjectOut:
    exists = await db.scalar(
        select(Project.id).where(
            Project.organization_id == user.organization_id, Project.slug == body.slug, Project.deleted_at.is_(None)
        )
    )
    if exists:
        raise ConflictError("A project with this slug already exists.", code="PROJECT_EXISTS")
    slugs = [e.slug for e in body.environments]
    if len(slugs) != len(set(slugs)):
        raise ValidationFailedError("Environment slugs must be unique.")
    project = Project(
        organization_id=user.organization_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        tag_values=body.tag_values,
    )
    db.add(project)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A project with this slug already exists.", code="PROJECT_EXISTS") from exc
    for i, env in enumerate(body.environments):
        db.add(
            Environment(
                organization_id=user.organization_id,
                project_id=project.id,
                name=env.name,
                slug=env.slug,
                kind=env.kind,
                sort_order=env.sort_order or i,
                tag_values=env.tag_values,
            )
        )
    await record_audit(
        db,
        action="project.created",
        user=user,
        target_type="project",
        target_id=str(project.id),
        request=request,
        details={"name": body.name, "slug": body.slug},
    )
    await db.flush()
    # New or changed tag values apply to existing resources straight away.
    await reassign_resources(db, user.organization_id)
    await db.commit()
    return (await _project_views(db, user, [await _get_project(db, user, project.id)]))[0]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, db: DbSession, user: Viewer) -> ProjectOut:
    return (await _project_views(db, user, [await _get_project(db, user, project_id)]))[0]


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, request: Request, db: DbSession, user: Manager
) -> ProjectOut:
    project = await _get_project(db, user, project_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(project, field, value)
    await record_audit(
        db,
        action="project.updated",
        user=user,
        target_type="project",
        target_id=str(project.id),
        request=request,
        details={"fields": sorted(changes)},
    )
    await db.flush()
    # New or changed tag values apply to existing resources straight away.
    await reassign_resources(db, user.organization_id)
    await db.commit()
    return (await _project_views(db, user, [await _get_project(db, user, project_id)]))[0]


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_project(project_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> None:
    project = await _get_project(db, user, project_id)
    now = datetime.now(UTC)
    project.deleted_at = now
    # Suffix the slug so it can be reused by a new project.
    project.slug = f"{project.slug[:60]}-deleted-{uuid.uuid4().hex[:8]}"
    for env in await db.scalars(select(Environment).where(Environment.project_id == project.id)):
        env.deleted_at = now
    for resource in await db.scalars(select(Resource).where(Resource.project_id == project.id)):
        resource.project_id = resource.environment_id = None
        resource.assignment_source = "none"
    await record_audit(
        db,
        action="project.deleted",
        user=user,
        target_type="project",
        target_id=str(project.id),
        request=request,
        details={"name": project.name},
    )
    await db.commit()


@router.post("/{project_id}/environments", response_model=EnvironmentOut, status_code=status.HTTP_201_CREATED)
async def create_environment(
    project_id: uuid.UUID, body: EnvironmentIn, request: Request, db: DbSession, user: Manager
) -> Environment:
    project = await _get_project(db, user, project_id)
    if any(e.slug == body.slug for e in project.environments):
        raise ConflictError("An environment with this slug already exists.", code="ENVIRONMENT_EXISTS")
    env = Environment(
        organization_id=user.organization_id,
        project_id=project.id,
        name=body.name,
        slug=body.slug,
        kind=body.kind,
        sort_order=body.sort_order or len(project.environments),
        tag_values=body.tag_values,
    )
    db.add(env)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("An environment with this slug already exists.", code="ENVIRONMENT_EXISTS") from exc
    await record_audit(
        db,
        action="environment.created",
        user=user,
        target_type="environment",
        target_id=str(env.id),
        request=request,
        details={"project": project.slug, "slug": body.slug},
    )
    await db.flush()
    # New or changed tag values apply to existing resources straight away.
    await reassign_resources(db, user.organization_id)
    await db.commit()
    return env


async def _get_env(db: DbSession, user: CurrentUser, project_id: uuid.UUID, env_id: uuid.UUID) -> Environment:
    env = await db.scalar(
        select(Environment).where(
            Environment.id == env_id,
            Environment.project_id == project_id,
            Environment.organization_id == user.organization_id,
            Environment.deleted_at.is_(None),
        )
    )
    if env is None:
        raise NotFoundError("Environment not found.")
    return env


@router.patch("/{project_id}/environments/{env_id}", response_model=EnvironmentOut)
async def update_environment(
    project_id: uuid.UUID,
    env_id: uuid.UUID,
    body: EnvironmentUpdate,
    request: Request,
    db: DbSession,
    user: Manager,
) -> Environment:
    env = await _get_env(db, user, project_id, env_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(env, field, value)
    await record_audit(
        db,
        action="environment.updated",
        user=user,
        target_type="environment",
        target_id=str(env.id),
        request=request,
        details={"fields": sorted(changes)},
    )
    await db.flush()
    # New or changed tag values apply to existing resources straight away.
    await reassign_resources(db, user.organization_id)
    await db.commit()
    return env


@router.delete("/{project_id}/environments/{env_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_environment(
    project_id: uuid.UUID, env_id: uuid.UUID, request: Request, db: DbSession, user: Manager
) -> None:
    env = await _get_env(db, user, project_id, env_id)
    env.deleted_at = datetime.now(UTC)
    env.slug = f"{env.slug[:60]}-deleted-{uuid.uuid4().hex[:8]}"
    for resource in await db.scalars(select(Resource).where(Resource.environment_id == env.id)):
        resource.environment_id = None
    await record_audit(
        db,
        action="environment.deleted",
        user=user,
        target_type="environment",
        target_id=str(env.id),
        request=request,
        details={"name": env.name},
    )
    await db.commit()


@router.get("/{project_id}/comparison", response_model=ComparisonOut)
async def environment_comparison(
    project_id: uuid.UUID,
    time_range: TimeRangeDep,
    db: DbSession,
    azure: Azure,
    user: Annotated[CurrentUser, Depends(require(Permission.view_dashboards))],
) -> ComparisonOut:
    project = await _get_project(db, user, project_id)
    return await compare_environments(db, azure, project, time_range)
