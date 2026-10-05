from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession, require
from app.core.permissions import Permission
from app.models import Environment, Project, Resource, Subscription
from app.schemas.misc import SearchHit, SearchOut
from app.services.monitors.registry import all_monitors, type_display_name

router = APIRouter(prefix="/search", tags=["search"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_resources))]

_ENV_WORDS = {
    "production": "production",
    "prod": "production",
    "development": "development",
    "dev": "development",
    "uat": "uat",
    "staging": "staging",
}


@router.get("", response_model=SearchOut)
async def search(
    db: DbSession,
    user: Viewer,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchOut:
    term = q.strip().lower()
    like = f"%{term}%"
    compact = term.replace(" ", "")
    org = user.organization_id
    hits: list[SearchHit] = []

    projects = {
        p.id: p
        for p in await db.scalars(select(Project).where(Project.organization_id == org, Project.deleted_at.is_(None)))
    }
    for p in projects.values():
        if term in p.name.lower() or term in p.slug or any(term == t.lower() for t in p.tag_values or []):
            hits.append(
                SearchHit(kind="project", id=str(p.id), title=p.name, subtitle="Project", url=f"/projects/{p.id}")
            )

    env_kind = _ENV_WORDS.get(term)
    env_query = select(Environment).where(Environment.organization_id == org, Environment.deleted_at.is_(None))
    env_query = env_query.where(
        or_(
            func.lower(Environment.name).like(like),
            Environment.slug.like(like),
            Environment.kind == (env_kind or "__none__"),
        )
    )
    for e in await db.scalars(env_query.limit(limit)):
        project = projects.get(e.project_id)
        if project:
            hits.append(
                SearchHit(
                    kind="environment",
                    id=str(e.id),
                    title=f"{project.name} / {e.name}",
                    subtitle="Environment",
                    url=f"/projects/{project.id}?environment={e.id}",
                )
            )

    for s in await db.scalars(
        select(Subscription).where(
            Subscription.organization_id == org,
            Subscription.deleted_at.is_(None),
            or_(func.lower(Subscription.display_name).like(like), Subscription.subscription_id.like(like)),
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

    # Match friendly type names ("Front Door", "App Service") to monitor keys.
    monitor_keys = [m.key for m in all_monitors() if term in m.display_name.lower()]
    conditions = [
        func.lower(Resource.name).like(like),
        func.lower(Resource.resource_group).like(like),
        Resource.resource_type.like(like),
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
        project = projects.get(r.project_id) if r.project_id else None
        scope = " / ".join(x for x in (project.name if project else None, r.resource_group) if x)
        hits.append(
            SearchHit(
                kind="resource",
                id=str(r.id),
                title=r.name,
                subtitle=f"{type_display_name(r.resource_type, r.monitor_key)} - {scope}",
                url=f"/resources/{r.id}",
                health_status=r.health_status,
            )
        )
    return SearchOut(query=q, hits=hits[: limit * 2])
