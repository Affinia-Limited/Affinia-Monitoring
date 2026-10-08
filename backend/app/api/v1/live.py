"""Live mode: per-resource status and minute-by-minute metrics for the resources on screen.

When Live is switched on, every page asks for the resources it is showing. Each resource's
health-rule metrics are read from Azure Monitor at 1-minute granularity over the last hour
and judged with the same rules, windows and thresholds as the health job. The live status
combines those readings with the non-metric signals of the last health evaluation (Azure
Resource Health and ARM state), so it moves as soon as a metric crosses a threshold instead
of waiting for the next scheduled evaluation.

The time range is aligned to the minute, so all viewers polling within the same minute
share one cached Azure read per metric.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import Azure, CurrentUser, DbSession, require
from app.core.errors import ValidationFailedError
from app.core.permissions import Permission
from app.models import AzureConnection, HealthThreshold, Resource
from app.services.azure.types import TimeRange
from app.services.health.evaluator import classify
from app.services.metric_service import MetricData, MetricService, reduce_values
from app.services.monitors.base import HealthRule
from app.services.monitors.registry import get_monitor
from app.services.views import UNMONITORED_KEYS, worst

router = APIRouter(prefix="/live", tags=["live"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_resources))]

WINDOW_MINUTES = 60
INTERVAL = timedelta(minutes=1)
#: Resources per request: one page of the largest resource table.
MAX_RESOURCES = 50


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
        # One value per minute, oldest first, ending at ``latest_at``'s minute or earlier. Timestamps are
        # implied by the response's window and interval, which keeps 5-second polls small.
        "values": [None if p["value"] is None else round(p["value"], 3) for p in points],
        "unavailable_reason": data.unavailable_reason,
    }


def _metric_reason(metric: dict[str, Any]) -> dict[str, Any]:
    """A live breach in the same shape as a stored health reason."""
    severity = metric["status"]
    return {
        "signal": "metric",
        "severity": severity,
        "metric": metric["key"],
        "label": metric["label"],
        "unit": metric["unit"],
        "value": round(metric["window_value"], 3),
        "operator": metric["operator"],
        "threshold": metric["critical"] if severity == "critical" else metric["warning"],
        "window_minutes": metric["window_minutes"],
        "message": metric["label"],
    }


def _live_status(resource: Resource, metrics: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Worst of the last evaluation's non-metric signals and the live metric readings."""
    reasons = [r for r in resource.health_reasons or [] if r.get("signal") != "metric"]
    reasons += [_metric_reason(m) for m in metrics if m["status"] in ("warning", "critical")]
    statuses = [r["severity"] for r in reasons]
    statuses += [m["status"] for m in metrics if m["status"] == "healthy"]
    # A resource the health job could read (e.g. Resource Health "Available") counts as a healthy signal.
    if resource.health_status != "unknown":
        statuses.append("healthy")
    return (worst(statuses) if statuses else "unknown"), reasons


@router.get("/resources")
async def live_resources(
    db: DbSession,
    azure: Azure,
    user: Viewer,
    ids: Annotated[str, Query(description="Comma-separated resource ids, at most 50")],
) -> dict[str, Any]:
    try:
        wanted = list(dict.fromkeys(uuid.UUID(v.strip()) for v in ids.split(",") if v.strip()))
    except ValueError as exc:
        raise ValidationFailedError("ids must be comma-separated resource ids.") from exc
    if len(wanted) > MAX_RESOURCES:
        raise ValidationFailedError(f"At most {MAX_RESOURCES} resources can be watched live at once.")

    org = user.organization_id
    rows = (
        list(
            await db.scalars(
                select(Resource).where(
                    Resource.organization_id == org, Resource.deleted_at.is_(None), Resource.id.in_(wanted)
                )
            )
        )
        if wanted
        else []
    )
    rows = [r for r in rows if r.monitor_key not in UNMONITORED_KEYS]

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
        plan: list[tuple[HealthRule, float | None, float | None]] = []
        for rule in monitor.health_rules:
            override = overrides.get((monitor.key, rule.metric))
            if (override is not None and not override.enabled) or any(p[0].metric == rule.metric for p in plan):
                continue
            if override is not None:
                plan.append((rule, override.warning_threshold, override.critical_threshold))
            else:
                plan.append((rule, rule.warning, rule.critical))
        plans.append(plan)

    end = datetime.now(UTC).replace(second=0, microsecond=0)
    time_range = TimeRange(start=end - timedelta(minutes=WINDOW_MINUTES), end=end, preset="live")
    requests = [
        (r, tenants.get(r.connection_id, ""), [rule.metric for rule, _, _ in plan])
        for r, plan in zip(rows, plans, strict=True)
    ]
    readings = await MetricService(db, azure).get_metrics_many(requests, time_range, INTERVAL)

    generated_at = datetime.now(UTC).isoformat()
    resources: dict[str, dict[str, Any]] = {}
    for r, plan, data in zip(rows, plans, readings, strict=True):
        metrics = [_live_metric(d, rule, w, c) for d, (rule, w, c) in zip(data, plan, strict=True)]
        status, reasons = _live_status(r, metrics)
        resources[str(r.id)] = {
            "id": str(r.id),
            "status": status,
            "reasons": reasons,
            "evaluated_status": r.health_status,
            "evaluated_at": r.health_evaluated_at.isoformat() if r.health_evaluated_at else None,
            "metrics": metrics,
            "checked_at": generated_at,
        }

    return {
        "is_mock": azure.is_mock,
        "generated_at": generated_at,
        "window_minutes": WINDOW_MINUTES,
        "interval_seconds": int(INTERVAL.total_seconds()),
        "resources": resources,
    }
