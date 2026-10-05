from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import Azure, CurrentUser, DbSession, require
from app.core.cache import cache_key, get_cache
from app.core.errors import AppError
from app.core.permissions import Permission
from app.models import Alert, AzureConnection, Project, Resource, Subscription
from app.services.monitors.registry import type_display_name
from app.services.views import (
    ScopeHealth,
    active_alert_counts_by_environment,
    active_alert_counts_by_project,
    alert_views,
    counts_for,
    health_by_scope,
    load_lookups,
    resource_view,
)

router = APIRouter(prefix="/overview", tags=["overview"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_dashboards))]


_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_MAX_REGIONS = 4


def _region_key(name: str) -> str:
    return name.replace(" ", "").lower()


def _who(changed_by: str | None) -> str | None:
    """Raw object ids mean an app or managed identity; show that instead of a GUID."""
    if not changed_by:
        return None
    return "Service principal" if _GUID.match(changed_by) else changed_by


async def _azure_feeds(db: DbSession, azure: Azure, user: CurrentUser, locations: set[str]) -> dict[str, Any]:
    """Service Health events and recent resource changes, per connection, cached for 5 minutes."""
    connections = list(
        await db.scalars(
            select(AzureConnection).where(
                AzureConnection.organization_id == user.organization_id, AzureConnection.deleted_at.is_(None)
            )
        )
    )
    cache = get_cache()
    service_health: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for connection in connections:
        subs = list(
            await db.scalars(
                select(Subscription.subscription_id).where(
                    Subscription.connection_id == connection.id, Subscription.deleted_at.is_(None)
                )
            )
        )
        if not subs:
            continue
        key = cache_key("overview_feeds", connection.tenant_id, sorted(subs))
        cached = await cache.get(key)
        if cached is None:
            cached = {"service_health": [], "changes": []}
            try:
                events = await azure.resource_graph.service_health(connection.tenant_id, subs)
                cached["service_health"] = [
                    {
                        "id": e.event_id,
                        "title": e.title,
                        "event_type": e.event_type,
                        "status": e.status,
                        "level": e.level,
                        "services": e.services,
                        "regions": e.regions,
                        "last_update": e.last_update.isoformat() if e.last_update else None,
                    }
                    for e in events
                ]
                recent = await azure.resource_graph.recent_changes(connection.tenant_id, subs, limit=25)
                cached["changes"] = [
                    {
                        "azure_id": c.azure_id,
                        "change_type": c.change_type,
                        "changed_at": c.changed_at.isoformat() if c.changed_at else None,
                        "changed_by": c.changed_by,
                        "operation": c.operation,
                    }
                    for c in recent
                ]
                await cache.set(key, cached, 300)
            except AppError as exc:
                errors.append({"connection": connection.name, "code": exc.code, "message": exc.message})
        service_health.extend(cached["service_health"])
        changes.extend(cached["changes"])

    # Service Health: relevant first (affects a region we have resources in, or global), then active.
    for event in service_health:
        regions = event.get("regions") or []
        event["relevant"] = any(r == "Global" or _region_key(r) in locations for r in regions) or not regions
        event["region_count"] = len(regions)
        relevant_regions = [r for r in regions if r == "Global" or _region_key(r) in locations]
        event["regions"] = (relevant_regions or regions)[:_MAX_REGIONS]
    service_health.sort(key=lambda e: e.get("last_update") or "", reverse=True)
    service_health.sort(key=lambda e: (not e["relevant"], e.get("status", "").lower() != "active"))
    service_health = [e for e in service_health if e["relevant"] or e.get("status", "").lower() == "active"]

    # Changes: only monitored resources, newest first; system databases and inventory items are noise.
    ids = {c["azure_id"] for c in changes}
    known = (
        {
            r.azure_id: r
            for r in await db.scalars(
                select(Resource).where(Resource.organization_id == user.organization_id, Resource.azure_id.in_(ids))
            )
        }
        if ids
        else {}
    )
    useful = []
    for c in changes:
        r = known.get(c["azure_id"])
        if r is None or r.monitor_key in (None, "generic"):
            continue
        c["resource_id"] = str(r.id)
        c["resource_name"] = r.name
        c["type_display_name"] = type_display_name(r.resource_type, r.monitor_key)
        c["changed_by"] = _who(c.get("changed_by"))
        useful.append(c)
    useful.sort(key=lambda c: c.get("changed_at") or "", reverse=True)
    return {"service_health": service_health[:10], "recent_changes": useful[:8], "feed_errors": errors}


@router.get("")
async def overview(db: DbSession, azure: Azure, user: Viewer) -> dict[str, Any]:
    org = user.organization_id
    resources = (
        await db.execute(
            select(
                Resource.project_id,
                Resource.environment_id,
                Resource.health_status,
                Resource.resource_type,
                Resource.monitor_key,
                Resource.location,
            ).where(Resource.organization_id == org, Resource.deleted_at.is_(None))
        )
    ).all()
    # Health figures cover monitored resources only; inventory items (NICs, DNS zones, ...) have no signals.
    monitored = [r for r in resources if r[4] not in (None, "generic")]
    projects = list(
        await db.scalars(
            select(Project)
            .where(Project.organization_id == org, Project.deleted_at.is_(None))
            .options(selectinload(Project.environments))
            .order_by(Project.name)
        )
    )
    subscriptions = await db.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.organization_id == org, Subscription.deleted_at.is_(None)
        )
    )
    connections = await db.scalar(
        select(func.count(AzureConnection.id)).where(
            AzureConnection.organization_id == org, AzureConnection.deleted_at.is_(None)
        )
    )
    alert_rows = (
        await db.execute(
            select(Alert.severity, func.count())
            .where(Alert.organization_id == org, Alert.status.in_(["active", "acknowledged"]))
            .group_by(Alert.severity)
        )
    ).all()
    recent_alerts = list(
        await db.scalars(
            select(Alert)
            .where(Alert.organization_id == org, Alert.status.in_(["active", "acknowledged"]))
            .order_by(Alert.started_at.desc())
            .limit(10)
        )
    )

    scopes = await health_by_scope(db, org)
    project_alerts = await active_alert_counts_by_project(db, org)
    env_alerts = await active_alert_counts_by_environment(db, org)
    env_status_counts = {"healthy": 0, "warning": 0, "critical": 0, "unknown": 0}
    project_health = []
    for p in projects:
        envs = []
        for e in p.environments:
            scope = scopes.get((p.id, e.id), ScopeHealth())
            env_status_counts[scope.status] = env_status_counts.get(scope.status, 0) + 1
            envs.append(
                {
                    "id": str(e.id),
                    "name": e.name,
                    "slug": e.slug,
                    "kind": e.kind,
                    "status": scope.status,
                    "counts": scope.counts.model_dump(),
                    "active_alerts": env_alerts.get((p.id, e.id), 0),
                    "last_checked_at": scope.last_checked_at.isoformat() if scope.last_checked_at else None,
                }
            )
        scope = scopes.get((p.id, None), ScopeHealth())
        project_health.append(
            {
                "id": str(p.id),
                "name": p.name,
                "slug": p.slug,
                "description": p.description,
                "status": scope.status,
                "counts": scope.counts.model_dump(),
                "active_alerts": project_alerts.get(p.id, 0),
                "last_checked_at": scope.last_checked_at.isoformat() if scope.last_checked_at else None,
                "environments": envs,
            }
        )
    last_synced = await db.scalar(
        select(func.max(AzureConnection.last_sync_at)).where(
            AzureConnection.organization_id == org, AzureConnection.deleted_at.is_(None)
        )
    )

    by_type: dict[str, dict[str, Any]] = {}
    for _, _, health, rtype, mkey, _ in monitored:
        label = type_display_name(rtype, mkey)
        entry = by_type.setdefault(
            label,
            {
                "label": label,
                "count": 0,
                "monitored": mkey != "generic",
                "counts": {"healthy": 0, "warning": 0, "critical": 0, "unknown": 0},
            },
        )
        entry["count"] += 1
        entry["counts"][health] = entry["counts"].get(health, 0) + 1

    attention_rows = list(
        await db.scalars(
            select(Resource)
            .where(
                Resource.organization_id == org,
                Resource.deleted_at.is_(None),
                Resource.monitor_key.notin_(["generic"]),
                Resource.health_status.in_(["critical", "warning"]),
            )
            .order_by(Resource.health_status.asc(), Resource.name)  # "critical" sorts before "warning"
            .limit(12)
        )
    )
    lookups = await load_lookups(db, org, attention_rows)
    needs_attention = []
    for r in attention_rows:
        view = resource_view(r, lookups)
        top = (r.health_reasons or [{}])[0]
        needs_attention.append(
            {
                "id": str(r.id),
                "name": r.name,
                "type_display_name": view.type_display_name,
                "project_name": view.project_name,
                "environment_name": view.environment_name,
                "health_status": r.health_status,
                "reason": _reason_text(top),
            }
        )

    locations = {loc for *_, loc in resources if loc}
    feeds = await _azure_feeds(db, azure, user, locations)
    return {
        "is_mock": azure.is_mock,
        "generated_at": datetime.now(UTC).isoformat(),
        "last_synced_at": last_synced.isoformat() if last_synced else None,
        #: Environments by their worst monitored-resource status (an empty environment is "unknown").
        "environment_health": env_status_counts,
        "totals": {
            "projects": len(projects),
            "environments": sum(len(p.environments) for p in projects),
            "subscriptions": int(subscriptions or 0),
            "connections": int(connections or 0),
            "resources": len(resources),
            "monitored_resources": len(monitored),
            "inventory_resources": len(resources) - len(monitored),
            "unassigned_resources": sum(1 for r in monitored if r[0] is None),
        },
        "health": counts_for([r[2] for r in monitored]).model_dump(),
        "needs_attention": needs_attention,
        "alerts": {"active": sum(int(n) for _, n in alert_rows), "by_severity": {sev: int(n) for sev, n in alert_rows}},
        "project_health": project_health,
        "recent_alerts": [a.model_dump(mode="json") for a in await alert_views(db, recent_alerts)],
        "resource_types": sorted(by_type.values(), key=lambda t: -t["count"]),
        **feeds,
    }


def _reason_text(reason: dict[str, Any]) -> str:
    if not reason:
        return ""
    if reason.get("signal") == "metric":
        unit = {"percent": "%", "milliseconds": " ms"}.get(reason.get("unit") or "", "")
        op = {"gt": "above", "gte": "at or above", "lt": "below", "lte": "at or below"}.get(
            reason.get("operator", ""), ""
        )
        return f"{reason.get('label')} {reason.get('value'):g}{unit}, {op} {reason.get('threshold'):g}{unit}"
    return str(reason.get("message") or "")
