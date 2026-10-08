"""Live monitoring: current status and minute-by-minute metrics, polled by the Live page.

Status comes from the stored health evaluation (Resource Health, ARM state and metric
rules, refreshed by the health job). Metrics are read from Azure Monitor on request at
1-minute granularity over the last hour. The time range is aligned to the minute, so
every viewer polling within the same minute shares one cached Azure read per metric.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import Azure, CurrentUser, DbSession, require
from app.core.permissions import Permission
from app.models import Alert, AzureConnection, HealthThreshold, Project, Resource
from app.services.azure.types import TimeRange
from app.services.health.evaluator import classify
from app.services.metric_service import MetricData, MetricService, reduce_values
from app.services.monitors.base import HealthRule
from app.services.monitors.registry import get_monitor
from app.services.views import (
    OPEN_ALERT_STATUSES,
    active_alert_counts_by_environment,
    alert_views,
    counts_for,
    health_by_scope,
    load_lookups,
    resource_view,
)

router = APIRouter(prefix="/live", tags=["live"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_dashboards))]

WINDOW_MINUTES = 60
INTERVAL = timedelta(minutes=1)
#: Resources with live metrics per response, worst health first. Bounds the Azure calls per poll.
MAX_RESOURCES = 24
METRICS_PER_RESOURCE = 3
#: Newest open alerts returned (the Live page's change feed relies on this limit).
RECENT_ALERTS = 8

_HEALTH_ORDER = case({"critical": 0, "warning": 1, "healthy": 2}, value=Resource.health_status, else_=3)


def _live_metric(data: MetricData, rule: HealthRule, warning: float | None, critical: float | None) -> dict[str, Any]:
    """Latest minute, the health rule's window value, and its status against the thresholds."""
    points = [p for s in data.series[:1] for p in s["points"]]
    latest = next((p for p in reversed(points) if p["value"] is not None), None)
    in_window = [p["value"] for p in points[-rule.window_minutes :] if p["value"] is not None]
    window_value = reduce_values(in_window, rule.reducer)
    return {
        "key": data.key,
        "label": data.label,
        "unit": data.unit,
        "latest": latest["value"] if latest else None,
        "latest_at": latest["timestamp"] if latest else None,
        "window_value": window_value,
        "window_minutes": rule.window_minutes,
        "reducer": rule.reducer,
        "operator": rule.operator,
        "warning": warning,
        "critical": critical,
        "status": classify(window_value, rule, warning, critical) if window_value is not None else "unknown",
        "points": [{"timestamp": p["timestamp"], "value": p["value"]} for p in points],
        "unavailable_reason": data.unavailable_reason,
    }


@router.get("")
async def live(
    db: DbSession,
    azure: Azure,
    user: Viewer,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    environment_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, Any]:
    org = user.organization_id
    in_scope = [
        Resource.organization_id == org,
        Resource.deleted_at.is_(None),
        Resource.monitor_key.is_not(None),
        Resource.monitor_key != "generic",
    ]
    if project_id:
        in_scope.append(Resource.project_id == project_id)
    if environment_id:
        in_scope.append(Resource.environment_id == environment_id)

    statuses = list(await db.scalars(select(Resource.health_status).where(*in_scope)))
    rows = list(
        await db.scalars(select(Resource).where(*in_scope).order_by(_HEALTH_ORDER, Resource.name).limit(MAX_RESOURCES))
    )

    # Environments in scope, with the same roll-up as the overview.
    project_query = select(Project).where(Project.organization_id == org, Project.deleted_at.is_(None))
    if project_id:
        project_query = project_query.where(Project.id == project_id)
    projects = list(await db.scalars(project_query.options(selectinload(Project.environments)).order_by(Project.name)))
    scopes = await health_by_scope(db, org, [p.id for p in projects])
    env_alerts = await active_alert_counts_by_environment(db, org)
    environments = []
    for p in projects:
        for e in p.environments:
            if environment_id and e.id != environment_id:
                continue
            scope = scopes.get((p.id, e.id))
            environments.append(
                {
                    "project_id": str(p.id),
                    "project_name": p.name,
                    "environment_id": str(e.id),
                    "environment_name": e.name,
                    "kind": e.kind,
                    "status": scope.status if scope else "unknown",
                    "counts": (scope.counts if scope else counts_for([])).model_dump(),
                    "active_alerts": env_alerts.get((p.id, e.id), 0),
                    "last_checked_at": scope.last_checked_at.isoformat() if scope and scope.last_checked_at else None,
                }
            )

    alert_scope = [Alert.organization_id == org, Alert.status.in_(OPEN_ALERT_STATUSES)]
    if project_id or environment_id:
        alert_scope.append(Alert.resource_id.in_(select(Resource.id).where(*in_scope)))
    severity_rows = await db.execute(select(Alert.severity, func.count()).where(*alert_scope).group_by(Alert.severity))
    by_severity = {sev: int(n) for sev, n in severity_rows.all()}
    recent_alerts = list(
        await db.scalars(select(Alert).where(*alert_scope).order_by(Alert.started_at.desc()).limit(RECENT_ALERTS))
    )

    # Live metrics: each resource's health-rule metrics, with organisation threshold overrides.
    overrides = {
        (t.monitor_key, t.metric_name): t
        for t in await db.scalars(select(HealthThreshold).where(HealthThreshold.organization_id == org))
    }
    connection_ids = {r.connection_id for r in rows}
    tenants = {
        c.id: c.tenant_id
        for c in await db.scalars(select(AzureConnection).where(AzureConnection.id.in_(connection_ids)))
    }
    plans: list[list[tuple[HealthRule, float | None, float | None]]] = []
    for r in rows:
        monitor = get_monitor(r.monitor_key)
        chosen: list[tuple[HealthRule, float | None, float | None]] = []
        for rule in monitor.health_rules:
            override = overrides.get((monitor.key, rule.metric))
            if (override is not None and not override.enabled) or any(c[0].metric == rule.metric for c in chosen):
                continue
            if override is not None:
                chosen.append((rule, override.warning_threshold, override.critical_threshold))
            else:
                chosen.append((rule, rule.warning, rule.critical))
        plans.append(chosen[:METRICS_PER_RESOURCE])

    end = datetime.now(UTC).replace(second=0, microsecond=0)
    time_range = TimeRange(start=end - timedelta(minutes=WINDOW_MINUTES), end=end, preset="live")
    requests = [
        (r, tenants.get(r.connection_id, ""), [rule.metric for rule, _, _ in plan])
        for r, plan in zip(rows, plans, strict=True)
    ]
    readings = await MetricService(db, azure).get_metrics_many(requests, time_range, INTERVAL)

    lookups = await load_lookups(db, org, rows)
    resources = []
    for r, plan, data in zip(rows, plans, readings, strict=True):
        view = resource_view(r, lookups)
        resources.append(
            {
                "id": str(r.id),
                "name": r.name,
                "type_display_name": view.type_display_name,
                "project_id": str(r.project_id) if r.project_id else None,
                "project_name": view.project_name,
                "environment_id": str(r.environment_id) if r.environment_id else None,
                "environment_name": view.environment_name,
                "health_status": r.health_status,
                "health_evaluated_at": r.health_evaluated_at.isoformat() if r.health_evaluated_at else None,
                "active_alerts": view.active_alerts,
                "metrics": [_live_metric(d, rule, w, c) for d, (rule, w, c) in zip(data, plan, strict=True)],
            }
        )

    return {
        "is_mock": azure.is_mock,
        "generated_at": datetime.now(UTC).isoformat(),
        "window_minutes": WINDOW_MINUTES,
        "interval_seconds": int(INTERVAL.total_seconds()),
        "health": counts_for(statuses).model_dump(),
        "alerts": {"active": sum(by_severity.values()), "by_severity": by_severity},
        "environments": environments,
        "resources": resources,
        "resources_total": len(statuses),
        "recent_alerts": [a.model_dump(mode="json") for a in await alert_views(db, recent_alerts)],
    }
