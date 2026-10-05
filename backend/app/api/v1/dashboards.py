from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.permissions import Permission
from app.models import Dashboard, DashboardTemplate, DashboardWidget, Environment, Project, Resource
from app.schemas.dashboards import DashboardOut, DashboardSummary, DashboardUpdate, TemplateOut, WidgetOut
from app.services.audit import record_audit
from app.services.dashboards.generator import build_widgets, sync_templates
from app.services.monitors.registry import get_monitor, type_display_name
from app.services.views import load_lookups

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_dashboards))]
Manager = Annotated[CurrentUser, Depends(require(Permission.manage_dashboards))]


async def _summaries(db: DbSession, user: CurrentUser, dashboards: list[Dashboard]) -> list[DashboardSummary]:
    resource_ids = [d.resource_id for d in dashboards if d.resource_id]
    resources = (
        {r.id: r for r in await db.scalars(select(Resource).where(Resource.id.in_(resource_ids)))}
        if resource_ids
        else {}
    )
    lookups = await load_lookups(db, user.organization_id, list(resources.values()))
    out = []
    for d in dashboards:
        s = DashboardSummary.model_validate(d)
        r = resources.get(d.resource_id) if d.resource_id else None
        if r:
            s.resource_type = r.resource_type
            s.type_display_name = type_display_name(r.resource_type, r.monitor_key)
            s.health_status = r.health_status
            p = lookups.projects.get(r.project_id) if r.project_id else None
            e = lookups.environments.get(r.environment_id) if r.environment_id else None
            s.project_name = p.name if p else None
            s.environment_name = e.name if e else None
            s.project_id = p.id if p else None
            s.environment_id = e.id if e else None
            s.environment_order = e.sort_order if e else None
            s.tags = dashboard_tags(r, p, e)
        out.append(s)
    return out


def _tag(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def dashboard_tags(resource: Resource, project: Project | None, env: Environment | None) -> list[str]:
    """Grafana-style tags derived from what the dashboard monitors (never typed by hand)."""
    monitor = get_monitor(resource.monitor_key)
    tags = ["azure", _tag(type_display_name(resource.resource_type, resource.monitor_key)), _tag(monitor.category)]
    if project:
        tags.append(project.slug)
    if env:
        tags.append(env.slug)
    return list(dict.fromkeys(t for t in tags if t))


async def _dashboard_out(db: DbSession, user: CurrentUser, dashboard: Dashboard) -> DashboardOut:
    [summary] = await _summaries(db, user, [dashboard])
    sections: list[str] = []
    for w in dashboard.widgets:
        if w.section not in sections:
            sections.append(w.section)
    return DashboardOut(
        **summary.model_dump(), widgets=[WidgetOut.model_validate(w) for w in dashboard.widgets], sections=sections
    )


async def _get(db: DbSession, user: CurrentUser, dashboard_id: uuid.UUID) -> Dashboard:
    dashboard = await db.scalar(
        select(Dashboard)
        .where(
            Dashboard.id == dashboard_id,
            Dashboard.organization_id == user.organization_id,
            Dashboard.deleted_at.is_(None),
        )
        .options(selectinload(Dashboard.widgets))
    )
    if dashboard is None:
        raise NotFoundError("Dashboard not found.")
    return dashboard


@router.get("", response_model=list[DashboardSummary])
async def list_dashboards(
    db: DbSession,
    user: Viewer,
    project_id: uuid.UUID | None = None,
    environment_id: uuid.UUID | None = None,
    monitor_key: Annotated[str | None, Query(max_length=60)] = None,
    include_generic: bool = False,
) -> list[DashboardSummary]:
    query = (
        select(Dashboard)
        .outerjoin(Resource, Resource.id == Dashboard.resource_id)
        .where(Dashboard.organization_id == user.organization_id, Dashboard.deleted_at.is_(None))
        .order_by(Dashboard.name)
    )
    if project_id:
        query = query.where(Resource.project_id == project_id)
    if environment_id:
        query = query.where(Resource.environment_id == environment_id)
    if monitor_key:
        query = query.where(Resource.monitor_key == monitor_key)
    elif not include_generic:
        query = query.where((Resource.monitor_key != "generic") | (Dashboard.resource_id.is_(None)))
    return await _summaries(db, user, list(await db.scalars(query)))


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(db: DbSession, user: Viewer) -> list[DashboardTemplate]:
    return list(await db.scalars(select(DashboardTemplate).order_by(DashboardTemplate.name)))


@router.get("/by-resource/{resource_id}", response_model=DashboardOut)
async def dashboard_for_resource(resource_id: uuid.UUID, db: DbSession, user: Viewer) -> DashboardOut:
    dashboard_id = await db.scalar(
        select(Dashboard.id).where(
            Dashboard.resource_id == resource_id,
            Dashboard.organization_id == user.organization_id,
            Dashboard.deleted_at.is_(None),
        )
    )
    if dashboard_id is None:
        raise NotFoundError("No dashboard has been generated for this resource yet.")
    return await _dashboard_out(db, user, await _get(db, user, dashboard_id))


@router.get("/{dashboard_id}", response_model=DashboardOut)
async def get_dashboard(dashboard_id: uuid.UUID, db: DbSession, user: Viewer) -> DashboardOut:
    return await _dashboard_out(db, user, await _get(db, user, dashboard_id))


@router.patch("/{dashboard_id}", response_model=DashboardOut)
async def update_dashboard(
    dashboard_id: uuid.UUID, body: DashboardUpdate, request: Request, db: DbSession, user: Manager
) -> DashboardOut:
    dashboard = await _get(db, user, dashboard_id)
    if body.name is not None:
        dashboard.name = body.name
    if body.widgets is not None:
        resource = await db.get(Resource, dashboard.resource_id) if dashboard.resource_id else None
        monitor = get_monitor(resource.monitor_key if resource else None)
        metric_keys = {m.key for m in monitor.metrics}
        query_keys = {q.key for q in monitor.log_queries}
        for w in body.widgets:
            refs = list(w.config.get("metrics", [])) + ([w.config["metric"]] if "metric" in w.config else [])
            if any(r not in metric_keys for r in refs):
                raise ValidationFailedError(f"Widget '{w.title}' references an unknown metric.")
            if "query" in w.config and w.config["query"] not in query_keys:
                raise ValidationFailedError(f"Widget '{w.title}' references an unknown log query.")
        dashboard.widgets.clear()
        await db.flush()
        dashboard.widgets.extend(
            DashboardWidget(
                position=i, section=w.section, widget_type=w.widget_type, title=w.title, width=w.width, config=w.config
            )
            for i, w in enumerate(body.widgets)
        )
        dashboard.is_customized = True
    await record_audit(
        db,
        action="dashboard.changed",
        user=user,
        target_type="dashboard",
        target_id=str(dashboard.id),
        request=request,
        details={"widgets": len(body.widgets) if body.widgets is not None else None},
    )
    await db.commit()
    return await _dashboard_out(db, user, await _get(db, user, dashboard_id))


@router.post("/{dashboard_id}/reset", response_model=DashboardOut)
async def reset_dashboard(dashboard_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> DashboardOut:
    dashboard = await _get(db, user, dashboard_id)
    resource = await db.get(Resource, dashboard.resource_id) if dashboard.resource_id else None
    if resource is None:
        raise ValidationFailedError("Only generated resource dashboards can be reset.")
    templates = await sync_templates(db)
    template = templates.get(resource.monitor_key or "generic") or templates["generic"]
    dashboard.widgets.clear()
    await db.flush()
    dashboard.widgets.extend(build_widgets(template))
    dashboard.template_id, dashboard.template_version, dashboard.is_customized = template.id, template.version, False
    await record_audit(
        db, action="dashboard.reset", user=user, target_type="dashboard", target_id=str(dashboard.id), request=request
    )
    await db.commit()
    return await _dashboard_out(db, user, await _get(db, user, dashboard_id))
