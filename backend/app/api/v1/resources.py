from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Select, case, func, or_, select

from app.api.deps import Azure, CurrentUser, DbSession, require
from app.api.v1.common import TimeRangeDep
from app.core.cache import cache_key, get_cache
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.permissions import Permission
from app.models import AzureConnection, Environment, Project, Resource, Subscription
from app.schemas.common import Page
from app.schemas.resources import (
    FacetValue,
    MetricCatalogEntry,
    MetricOut,
    MetricsResponse,
    ResourceAssignment,
    ResourceDetail,
    ResourceFacets,
    ResourceOut,
)
from app.services.audit import record_audit
from app.services.health.evaluator import evaluate_resources
from app.services.metric_service import MetricService
from app.services.monitors.registry import all_monitors, get_monitor, type_display_name
from app.services.relations import related_resource, related_resources, resource_in_org, tenant_for_resource
from app.services.views import load_lookups, resource_view

router = APIRouter(prefix="/resources", tags=["resources"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_resources))]
DashboardViewer = Annotated[CurrentUser, Depends(require(Permission.view_dashboards))]
Manager = Annotated[CurrentUser, Depends(require(Permission.manage_projects))]
#: Re-evaluation calls Azure, so it is limited to roles that may trigger syncs.
Syncer = Annotated[CurrentUser, Depends(require(Permission.sync_azure))]

_HEALTH_PATTERN = r"^(healthy|warning|critical|unknown)(,(healthy|warning|critical|unknown))*$"

# Severity order (critical first) rather than alphabetical.
_HEALTH_ORDER = case({"critical": 0, "warning": 1, "unknown": 2, "healthy": 3}, value=Resource.health_status, else_=4)

_SORTS = {
    "name": Resource.name,
    "type": Resource.resource_type,
    "health": _HEALTH_ORDER,
    "location": Resource.location,
    "last_seen": Resource.last_seen_at,
}


def _apply_filters(
    query: Select,  # type: ignore[type-arg]
    *,
    project_id: uuid.UUID | None,
    environment_id: uuid.UUID | None,
    subscription_id: str | None,
    resource_group: str | None,
    resource_type: str | None,
    monitor_key: str | None,
    location: str | None,
    health: str | None,
    q: str | None,
    unassigned: bool,
) -> Select:  # type: ignore[type-arg]
    if project_id:
        query = query.where(Resource.project_id == project_id)
    if unassigned:
        query = query.where(Resource.project_id.is_(None))
    if environment_id:
        query = query.where(Resource.environment_id == environment_id)
    if subscription_id:
        query = query.where(Resource.subscription_id == subscription_id.lower())
    if resource_group:
        query = query.where(func.lower(Resource.resource_group) == resource_group.lower())
    if resource_type:
        query = query.where(Resource.resource_type == resource_type.lower())
    if monitor_key:
        query = query.where(Resource.monitor_key.in_(monitor_key.split(",")))
    if location:
        query = query.where(Resource.location == location.lower().replace(" ", ""))
    if health:
        query = query.where(Resource.health_status.in_(health.split(",")))
    if q:
        term = f"%{q.lower().strip()}%"
        query = query.where(
            or_(
                func.lower(Resource.name).like(term),
                func.lower(Resource.resource_group).like(term),
                Resource.resource_type.like(term),
            )
        )
    return query


def resource_filters(
    project_id: uuid.UUID | None = None,
    environment_id: uuid.UUID | None = None,
    subscription_id: Annotated[str | None, Query(max_length=64)] = None,
    resource_group: Annotated[str | None, Query(max_length=200)] = None,
    resource_type: Annotated[str | None, Query(max_length=200)] = None,
    monitor_key: Annotated[str | None, Query(max_length=400)] = None,
    location: Annotated[str | None, Query(max_length=60)] = None,
    health: Annotated[str | None, Query(pattern=_HEALTH_PATTERN)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    unassigned: bool = False,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "environment_id": environment_id,
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "resource_type": resource_type,
        "monitor_key": monitor_key,
        "location": location,
        "health": health,
        "q": q,
        "unassigned": unassigned,
    }


Filters = Annotated[dict[str, Any], Depends(resource_filters)]


def _base(user: CurrentUser) -> Select:  # type: ignore[type-arg]
    return select(Resource).where(Resource.organization_id == user.organization_id, Resource.deleted_at.is_(None))


@router.get("", response_model=Page[ResourceOut])
async def list_resources(
    db: DbSession,
    user: Viewer,
    filters: Filters,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    sort: Annotated[str, Query(pattern=r"^-?(name|type|health|location|last_seen)$")] = "name",
    monitored_only: bool = False,
) -> Page[ResourceOut]:
    query = _apply_filters(_base(user), **filters)
    if monitored_only:
        query = query.where(Resource.monitor_key != "generic")
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    column = _SORTS[sort.lstrip("-")]
    query = query.order_by(column.desc() if sort.startswith("-") else column.asc(), Resource.name)
    resources = list(await db.scalars(query.offset((page - 1) * page_size).limit(page_size)))
    lookups = await load_lookups(db, user.organization_id, resources)
    return Page(
        items=[resource_view(r, lookups) for r in resources], total=int(total or 0), page=page, page_size=page_size
    )


@router.get("/facets", response_model=ResourceFacets)
async def resource_facets(
    db: DbSession, user: Viewer, filters: Filters, monitored_only: bool = False
) -> ResourceFacets:
    query = _apply_filters(_base(user), **filters)
    if monitored_only:
        query = query.where(Resource.monitor_key != "generic")
    base = query.subquery()

    async def facet(column: str) -> list[tuple[str, int]]:
        col = base.c[column]
        rows = await db.execute(select(col, func.count()).group_by(col).order_by(func.count().desc()))
        return [(v, int(n)) for v, n in rows.all() if v]

    type_rows = await db.execute(
        select(base.c.resource_type, base.c.monitor_key, func.count()).group_by(
            base.c.resource_type, base.c.monitor_key
        )
    )
    types: dict[str, FacetValue] = {}
    for rtype, mkey, n in type_rows.all():
        label = type_display_name(rtype, mkey)
        existing = types.get(rtype)
        types[rtype] = FacetValue(value=rtype, label=label, count=int(n) + (existing.count if existing else 0))
    subs = {
        s.subscription_id: s.display_name
        for s in await db.scalars(select(Subscription).where(Subscription.organization_id == user.organization_id))
    }
    return ResourceFacets(
        resource_types=sorted(types.values(), key=lambda f: -f.count),
        locations=[FacetValue(value=v, label=v, count=n) for v, n in await facet("location")],
        resource_groups=[FacetValue(value=v, label=v, count=n) for v, n in await facet("resource_group")],
        subscriptions=[FacetValue(value=v, label=subs.get(v, v), count=n) for v, n in await facet("subscription_id")],
        health=[FacetValue(value=v, label=v.title(), count=n) for v, n in await facet("health_status")],
    )


@router.get("/monitors", response_model=list[dict[str, object]])
async def list_monitors(user: Viewer) -> list[dict[str, object]]:
    """Supported resource types and their metric catalogues (used by alert rule forms)."""
    return [
        {
            "key": m.key,
            "display_name": m.display_name,
            "category": m.category,
            "resource_types": list(m.resource_types),
            "metrics": [
                {"key": d.key, "label": d.label, "unit": d.unit, "aggregation": d.aggregation}
                for d in m.metrics
                if not d.split_by
            ],
        }
        for m in all_monitors()
    ]


async def _resource(db: DbSession, user: CurrentUser, resource_id: uuid.UUID) -> Resource:
    resource = await resource_in_org(db, user.organization_id, resource_id)
    if resource is None:
        raise NotFoundError("Resource not found.")
    return resource


@router.get("/{resource_id}", response_model=ResourceDetail)
async def get_resource(resource_id: uuid.UUID, db: DbSession, user: Viewer) -> ResourceDetail:
    resource = await _resource(db, user, resource_id)
    lookups = await load_lookups(db, user.organization_id, [resource])
    base = resource_view(resource, lookups)
    monitor = get_monitor(resource.monitor_key)
    related: dict[str, uuid.UUID | None] = {}
    for relation in monitor.related(resource.resource_type, resource.azure_id, resource.properties or {}):
        target = await related_resource(db, resource, relation)
        related[relation] = target.id if target else None
    connection = await db.get(AzureConnection, resource.connection_id)
    tenant = connection.tenant_id if connection else ""
    return ResourceDetail(
        **base.model_dump(),
        properties=resource.properties or {},
        related=related,
        summary_metrics=list(monitor.summary_metrics),
        portal_url=f"https://portal.azure.com/#@{tenant}/resource{resource.azure_id}",
    )


@router.get("/{resource_id}/metric-definitions", response_model=list[MetricCatalogEntry])
async def metric_definitions(resource_id: uuid.UUID, db: DbSession, user: Viewer) -> list[MetricCatalogEntry]:
    resource = await _resource(db, user, resource_id)
    return [
        MetricCatalogEntry(
            key=m.key,
            label=m.label,
            unit=m.unit,
            aggregation=m.aggregation,
            split_by=m.split_by,
            target=m.target,
            description=m.description,
        )
        for m in get_monitor(resource.monitor_key).metrics
    ]


@router.get("/{resource_id}/metrics", response_model=MetricsResponse)
async def resource_metrics(
    resource_id: uuid.UUID,
    db: DbSession,
    azure: Azure,
    user: DashboardViewer,
    time_range: TimeRangeDep,
    metrics: Annotated[str, Query(max_length=1000, description="Comma-separated metric keys")],
) -> MetricsResponse:
    resource = await _resource(db, user, resource_id)
    keys = [k.strip() for k in metrics.split(",") if k.strip()]
    if not keys or len(keys) > 20:
        raise ValidationFailedError("Request between 1 and 20 metrics.")
    tenant = await tenant_for_resource(db, resource)
    data = await MetricService(db, azure).get_metrics(resource, tenant, keys, time_range)
    return MetricsResponse(
        resource_id=resource.id,
        start=time_range.start,
        end=time_range.end,
        metrics=[MetricOut(**d.to_dict()) for d in data],
    )


@router.get("/{resource_id}/related/{relation}", response_model=list[ResourceOut])
async def resource_related(resource_id: uuid.UUID, relation: str, db: DbSession, user: Viewer) -> list[ResourceOut]:
    if relation not in {"children", "apps_on_plan", "app_service_plan", "app_insights"}:
        raise NotFoundError("Unknown relation.")
    resource = await _resource(db, user, resource_id)
    items = await related_resources(db, resource, relation)
    lookups = await load_lookups(db, user.organization_id, items)
    return [resource_view(r, lookups) for r in items]


@router.put("/{resource_id}/assignment", response_model=ResourceOut)
async def assign_resource(
    resource_id: uuid.UUID, body: ResourceAssignment, request: Request, db: DbSession, user: Manager
) -> ResourceOut:
    resource = await _resource(db, user, resource_id)
    if body.project_id:
        project = await db.scalar(
            select(Project).where(
                Project.id == body.project_id,
                Project.organization_id == user.organization_id,
                Project.deleted_at.is_(None),
            )
        )
        if project is None:
            raise ValidationFailedError("Project not found.")
    if body.environment_id:
        env = await db.scalar(
            select(Environment).where(
                Environment.id == body.environment_id,
                Environment.organization_id == user.organization_id,
                Environment.deleted_at.is_(None),
            )
        )
        if env is None or env.project_id != body.project_id:
            raise ValidationFailedError("The environment must belong to the selected project.")
    resource.project_id, resource.environment_id = body.project_id, body.environment_id
    # "manual" pins the assignment; clearing it lets tag-based mapping take over on the next sync.
    resource.assignment_source = "manual" if body.project_id else "none"
    await record_audit(
        db,
        action="resource.assignment_changed",
        user=user,
        target_type="resource",
        target_id=resource.azure_id,
        request=request,
        details={
            "project_id": str(body.project_id) if body.project_id else None,
            "environment_id": str(body.environment_id) if body.environment_id else None,
        },
    )
    await db.commit()
    lookups = await load_lookups(db, user.organization_id, [resource])
    return resource_view(resource, lookups)


@router.post("/{resource_id}/health/evaluate", response_model=ResourceOut)
async def reevaluate_health(resource_id: uuid.UUID, db: DbSession, azure: Azure, user: Syncer) -> ResourceOut:
    resource = await _resource(db, user, resource_id)
    await evaluate_resources(db, azure, user.organization_id, resource_ids=[resource.id])
    await db.commit()
    lookups = await load_lookups(db, user.organization_id, [resource])
    return resource_view(resource, lookups)


@router.get("/{resource_id}/activity", response_model=list[dict[str, object]])
async def resource_activity(
    resource_id: uuid.UUID, db: DbSession, azure: Azure, user: Viewer
) -> list[dict[str, object]]:
    """Recent Azure changes for this resource (Resource Graph change history, last 7 days)."""
    resource = await _resource(db, user, resource_id)
    tenant = await tenant_for_resource(db, resource)
    key = cache_key("changes", tenant, resource.subscription_id)
    cache = get_cache()
    changes = await cache.get(key)
    if changes is None:
        items = await azure.resource_graph.recent_changes(tenant, [resource.subscription_id], limit=200)
        changes = [
            {
                "azure_id": c.azure_id,
                "change_type": c.change_type,
                "changed_at": c.changed_at.isoformat() if c.changed_at else None,
                "changed_by": c.changed_by,
                "operation": c.operation,
            }
            for c in items
        ]
        await cache.set(key, changes, 300)
    return [c for c in changes if c["azure_id"] == resource.azure_id][:50]
