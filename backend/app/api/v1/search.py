"""Global search across projects, environments, resources, open alerts and subscriptions.

Every hit carries its context (project, environment, resource type) so results such as
``app-crm-prod-uks`` are never ambiguous. Compound terms are understood: ``crm-prod`` or
``crm production`` matches the project and its production environment.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession, require
from app.core.permissions import Permission
from app.models import Alert, Environment, Project, Resource, Subscription
from app.schemas.misc import SearchHit, SearchOut
from app.services.monitors.registry import all_monitors, type_display_name
from app.services.views import OPEN_ALERT_STATUSES

router = APIRouter(prefix="/search", tags=["search"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_resources))]

#: Common shorthand mapped to environment kinds.
_ENV_WORDS = {
    "production": "production",
    "prod": "production",
    "prd": "production",
    "development": "development",
    "dev": "development",
    "uat": "uat",
    "staging": "staging",
    "stg": "staging",
}
_TOKEN_SPLIT = re.compile(r"[\s\-_/.]+")
_ALERT_LIMIT = 5
_LOG_SHORTCUTS = 3


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _env_matches(env: Environment, token: str) -> bool:
    return token in (env.slug, env.name.lower()) or _ENV_WORDS.get(token) == env.kind


@router.get("", response_model=SearchOut)
async def search(
    db: DbSession,
    user: Viewer,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchOut:
    term = q.strip().lower()
    like = f"%{_escape_like(term)}%"
    compact = term.replace(" ", "")
    tokens = [t for t in _TOKEN_SPLIT.split(term) if t]
    org = user.organization_id
    hits: list[SearchHit] = []

    projects = {
        p.id: p
        for p in await db.scalars(select(Project).where(Project.organization_id == org, Project.deleted_at.is_(None)))
    }
    environments = {
        e.id: e
        for e in await db.scalars(
            select(Environment).where(Environment.organization_id == org, Environment.deleted_at.is_(None))
        )
        if e.project_id in projects
    }

    def project_matches(p: Project) -> bool:
        names = {p.name.lower(), p.slug, *(t.lower() for t in p.tag_values or [])}
        return term in p.name.lower() or term in p.slug or any(t in names for t in tokens)

    matched_projects = {pid for pid, p in projects.items() if project_matches(p)}
    for pid in sorted(matched_projects, key=lambda i: projects[i].name.lower()):
        p = projects[pid]
        hits.append(SearchHit(kind="project", id=str(p.id), title=p.name, subtitle="Project", url=f"/projects/{p.id}"))

    # "crm-prod": a matched project plus an environment token narrows to that environment.
    env_hits: list[Environment] = []
    for e in sorted(environments.values(), key=lambda x: (projects[x.project_id].name.lower(), x.sort_order)):
        whole = term in e.name.lower() or term in e.slug or _ENV_WORDS.get(term) == e.kind
        scoped = e.project_id in matched_projects and any(_env_matches(e, t) for t in tokens)
        if whole or scoped:
            env_hits.append(e)
    for e in env_hits[:limit]:
        project = projects[e.project_id]
        hits.append(
            SearchHit(
                kind="environment",
                id=str(e.id),
                title=f"{project.name} / {e.name}",
                subtitle="Environment",
                url=f"/projects/{project.id}/environments/{e.id}",
                project_name=project.name,
                environment_name=e.name,
            )
        )

    # Match friendly type names ("Front Door", "App Service") to monitor keys.
    monitor_keys = [m.key for m in all_monitors() if term in m.display_name.lower()]
    conditions = [
        func.lower(Resource.name).like(like, escape="\\"),
        func.lower(Resource.resource_group).like(like, escape="\\"),
        Resource.resource_type.like(like, escape="\\"),
        Resource.location == compact,
    ]
    if monitor_keys:
        conditions.append(Resource.monitor_key.in_(monitor_keys))
    resources = list(
        await db.scalars(
            select(Resource)
            .where(Resource.organization_id == org, Resource.deleted_at.is_(None), or_(*conditions))
            .order_by(Resource.name)
            .limit(limit)
        )
    )
    for r in resources:
        owner = projects.get(r.project_id) if r.project_id else None
        env = environments.get(r.environment_id) if r.environment_id else None
        type_name = type_display_name(r.resource_type, r.monitor_key)
        scope = " / ".join(x for x in (owner.name if owner else None, env.name if env else None) if x)
        hits.append(
            SearchHit(
                kind="resource",
                id=str(r.id),
                title=r.name,
                subtitle=f"{type_name} - {scope or 'Unassigned'}",
                url=f"/resources/{r.id}",
                health_status=r.health_status,
                project_name=owner.name if owner else None,
                environment_name=env.name if env else None,
                type_display_name=type_name,
            )
        )

    alert_rows = (
        await db.execute(
            select(Alert, Resource)
            .join(Resource, Resource.id == Alert.resource_id)
            .where(
                Alert.organization_id == org,
                Alert.status.in_(OPEN_ALERT_STATUSES),
                or_(func.lower(Alert.title).like(like, escape="\\"), func.lower(Resource.name).like(like, escape="\\")),
            )
            .order_by(Alert.started_at.desc())
            .limit(_ALERT_LIMIT)
        )
    ).all()
    for alert, r in alert_rows:
        owner = projects.get(r.project_id) if r.project_id else None
        env = environments.get(r.environment_id) if r.environment_id else None
        hits.append(
            SearchHit(
                kind="alert",
                id=str(alert.id),
                title=alert.title,
                subtitle=f"{alert.severity.title()} alert on {r.name}",
                url=f"/alerts?alert={alert.id}",
                severity=alert.severity,
                project_name=owner.name if owner else None,
                environment_name=env.name if env else None,
                type_display_name=type_display_name(r.resource_type, r.monitor_key),
            )
        )

    # Log shortcuts for the environments found above.
    for e in env_hits[:_LOG_SHORTCUTS]:
        project = projects[e.project_id]
        hits.append(
            SearchHit(
                kind="logs",
                id=f"logs-{e.id}",
                title=f"Logs for {project.name} / {e.name}",
                subtitle="Log Analytics and Application Insights queries",
                url=f"/logs?project={project.id}&env={e.id}",
                project_name=project.name,
                environment_name=e.name,
            )
        )

    for s in await db.scalars(
        select(Subscription).where(
            Subscription.organization_id == org,
            Subscription.deleted_at.is_(None),
            or_(
                func.lower(Subscription.display_name).like(like, escape="\\"),
                Subscription.subscription_id.like(like, escape="\\"),
            ),
        )
    ):
        hits.append(
            SearchHit(
                kind="subscription",
                id=s.subscription_id,
                title=s.display_name or s.subscription_id,
                subtitle=f"Subscription {s.subscription_id}",
                url="/azure-connections",
            )
        )
    return SearchOut(query=q, hits=hits[: limit * 2])
