"""Dashboard template engine.

Templates come from monitor plugins and are upserted into ``dashboard_templates``
with a version. Each discovered resource gets one generated dashboard built from
its monitor's template. When a template's version increases, generated
dashboards are rebuilt unless a user has customised them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Dashboard, DashboardTemplate, DashboardWidget, Resource
from app.services.monitors.registry import all_monitors


async def sync_templates(db: AsyncSession) -> dict[str, DashboardTemplate]:
    existing = {t.key: t for t in await db.scalars(select(DashboardTemplate))}
    for monitor in all_monitors():
        key = f"{monitor.key}.default"
        template = existing.get(key)
        if template is None:
            template = DashboardTemplate(key=key, monitor_key=monitor.key, is_builtin=True)
            db.add(template)
            existing[key] = template
        definition = monitor.template()
        if template.definition != definition or (template.version or 0) < monitor.template_version:
            # Stored versions only move forward, so any template change reaches generated dashboards.
            template.version = max((template.version or 0) + 1, monitor.template_version)
            template.definition = definition
        template.name = f"{monitor.display_name} dashboard"
        template.description = f"Default dashboard for {monitor.display_name} resources."
        template.resource_types = list(monitor.resource_types)
    await db.flush()
    return {t.monitor_key: t for t in existing.values()}


def build_widgets(template: DashboardTemplate) -> list[DashboardWidget]:
    widgets: list[DashboardWidget] = []
    position = 0
    for section in template.definition.get("sections", []):
        for w in section.get("widgets", []):
            widgets.append(
                DashboardWidget(
                    position=position,
                    section=section["title"],
                    widget_type=w["type"],
                    title=w["title"],
                    width=int(w.get("width", 6)),
                    config=dict(w.get("config", {})),
                )
            )
            position += 1
    return widgets


async def generate_dashboards(
    db: AsyncSession, organization_id: uuid.UUID, connection_id: uuid.UUID | None = None
) -> dict[str, int]:
    templates = await sync_templates(db)
    query = select(Resource).where(Resource.organization_id == organization_id)
    if connection_id:
        query = query.where(Resource.connection_id == connection_id)
    resources = list(await db.scalars(query))
    dashboards = {
        d.resource_id: d
        for d in await db.scalars(
            select(Dashboard)
            .where(Dashboard.organization_id == organization_id, Dashboard.resource_id.in_([r.id for r in resources]))
            .options(selectinload(Dashboard.widgets))
        )
    }
    stats = {"dashboards_created": 0, "dashboards_updated": 0, "dashboards_archived": 0}
    now = datetime.now(UTC)
    for resource in resources:
        dashboard = dashboards.get(resource.id)
        if resource.deleted_at is not None:
            if dashboard and dashboard.deleted_at is None:
                dashboard.deleted_at = now
                stats["dashboards_archived"] += 1
            continue
        template = templates.get(resource.monitor_key or "generic") or templates["generic"]
        if dashboard is None:
            dashboard = Dashboard(
                organization_id=organization_id,
                name=resource.name,
                description=template.name,
                kind="resource",
                resource_id=resource.id,
                template_id=template.id,
                template_version=template.version,
                widgets=build_widgets(template),
            )
            db.add(dashboard)
            stats["dashboards_created"] += 1
            continue
        dashboard.deleted_at = None
        dashboard.name = resource.name
        needs_rebuild = dashboard.template_id != template.id or (dashboard.template_version or 0) < template.version
        if needs_rebuild and not dashboard.is_customized:
            dashboard.template_id = template.id
            dashboard.template_version = template.version
            dashboard.description = template.name
            dashboard.widgets.clear()
            await db.flush()
            dashboard.widgets.extend(build_widgets(template))
            stats["dashboards_updated"] += 1
    await db.flush()
    return stats
