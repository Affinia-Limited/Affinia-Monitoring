"""Resource health evaluation from real monitoring signals.

Signals, in order of precedence:

1. Azure Resource Health availability state (Unavailable -> critical, Degraded -> warning)
2. Resource state reported by ARM (e.g. a stopped App Service, an offline database)
3. Metric health rules from the resource's monitor plugin, with per-organisation
   threshold overrides (``health_thresholds``)

Status is ``unknown`` when no signal could be read at all. Health is never
invented: missing data is reported as missing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_key, get_cache
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.metrics import JOB_FAILURES, JOB_RUNS
from app.db.session import session_scope
from app.models import AzureConnection, HealthThreshold, Resource, Subscription
from app.services.azure.provider import get_azure_services
from app.services.azure.resource_health import health_from_availability
from app.services.azure.types import AzureServices, TimeRange
from app.services.metric_service import MetricService, reduce_values
from app.services.monitors.base import HealthRule, Operator
from app.services.monitors.registry import get_monitor

logger = logging.getLogger(__name__)

_RANK = {"healthy": 0, "unknown": 0, "warning": 1, "critical": 2}
_BAD_SQL_STATES = {"offline", "disabled", "suspect", "inaccessible", "emergencymode", "shutdown"}


def breaches(value: float, operator: Operator, threshold: float | None) -> bool:
    if threshold is None:
        return False
    return {
        "gt": value > threshold,
        "gte": value >= threshold,
        "lt": value < threshold,
        "lte": value <= threshold,
    }[operator]


def classify(value: float, rule: HealthRule, warning: float | None, critical: float | None) -> str:
    if breaches(value, rule.operator, critical):
        return "critical"
    if breaches(value, rule.operator, warning):
        return "warning"
    return "healthy"


def state_reasons(resource: Resource) -> list[dict[str, Any]]:
    props = resource.properties or {}
    reasons: list[dict[str, Any]] = []
    if resource.resource_type == "microsoft.web/sites" and str(props.get("state", "")).lower() == "stopped":
        reasons.append({"signal": "state", "severity": "warning", "message": "The app is stopped."})
    if (
        resource.resource_type == "microsoft.sql/servers/databases"
        and str(props.get("status", "")).lower() in _BAD_SQL_STATES
    ):
        reasons.append(
            {"signal": "state", "severity": "critical", "message": f"Database status is {props.get('status')}."}
        )
    if str(props.get("provisioningState", "")).lower() == "failed":
        reasons.append({"signal": "state", "severity": "warning", "message": "Provisioning state is Failed."})
    return reasons


async def _availability(
    db: AsyncSession, azure: AzureServices, connection: AzureConnection
) -> dict[str, dict[str, Any]]:
    subs = list(
        await db.scalars(
            select(Subscription.subscription_id).where(
                Subscription.connection_id == connection.id, Subscription.deleted_at.is_(None)
            )
        )
    )
    if not subs:
        return {}
    key = cache_key("resource_health", connection.tenant_id, sorted(subs))
    cache = get_cache()
    cached = await cache.get(key)
    if cached is not None:
        return dict(cached)
    try:
        states = await azure.resource_graph.resource_health(connection.tenant_id, subs)
    except AppError as exc:
        logger.warning("resource_health_unavailable", extra={"error_code": exc.code})
        return {}
    result = {s.azure_id: {"state": s.availability_state, "summary": s.summary} for s in states}
    await cache.set(key, result, get_settings().cache_ttl_health)
    return result


async def evaluate_resources(
    db: AsyncSession,
    azure: AzureServices,
    organization_id: uuid.UUID,
    connection_id: uuid.UUID | None = None,
    resource_ids: list[uuid.UUID] | None = None,
) -> dict[str, int]:
    query = select(Resource).where(Resource.organization_id == organization_id, Resource.deleted_at.is_(None))
    if connection_id:
        query = query.where(Resource.connection_id == connection_id)
    if resource_ids:
        query = query.where(Resource.id.in_(resource_ids))
    resources = list(await db.scalars(query))

    overrides = {
        (t.monitor_key, t.metric_name): t
        for t in await db.scalars(select(HealthThreshold).where(HealthThreshold.organization_id == organization_id))
    }
    connections = {
        c.id: c
        for c in await db.scalars(
            select(AzureConnection).where(AzureConnection.id.in_({r.connection_id for r in resources}))
        )
    }
    availability: dict[uuid.UUID, dict[str, dict[str, Any]]] = {}
    for conn in connections.values():
        availability[conn.id] = await _availability(db, azure, conn)

    # Every (resource, rule) metric is read up front, concurrently and batched (see MetricService).
    plans: dict[uuid.UUID, list[tuple[HealthRule, float | None, float | None]]] = {}
    for resource in resources:
        monitor = get_monitor(resource.monitor_key)
        plan = []
        for rule in monitor.health_rules:
            override = overrides.get((monitor.key, rule.metric))
            if override is not None and not override.enabled:
                continue
            warning = override.warning_threshold if override else rule.warning
            critical = override.critical_threshold if override else rule.critical
            plan.append((rule, warning, critical))
        plans[resource.id] = plan
    values = await _rule_values(db, azure, resources, connections, plans)

    stats = {"evaluated": 0, "healthy": 0, "warning": 0, "critical": 0, "unknown": 0}
    for resource in resources:
        connection = connections[resource.connection_id]
        monitor = get_monitor(resource.monitor_key)
        reasons: list[dict[str, Any]] = []
        readings: list[dict[str, Any]] = []
        signals = 0

        rh = availability.get(connection.id, {}).get(resource.azure_id)
        resource.azure_availability_state = rh["state"] if rh else None
        level = health_from_availability(rh["state"]) if rh else None
        if rh is not None and level is not None and level != "unknown":
            signals += 1
            if level != "healthy":
                reasons.append(
                    {
                        "signal": "resource_health",
                        "severity": level,
                        "message": rh.get("summary") or f"Azure Resource Health reports {rh['state']}.",
                    }
                )

        state = state_reasons(resource)
        reasons.extend(state)
        signals += 1 if state or resource.properties.get("state") or resource.properties.get("status") else 0

        previous_reasons = {r.get("metric"): r for r in resource.health_reasons or [] if r.get("signal") == "metric"}
        previous_readings = {r.get("metric"): r for r in resource.health_metrics or []}
        for rule, warning, critical in plans[resource.id]:
            value, failed = values[(resource.id, rule.metric)]
            if failed:
                # Azure could not be read (throttling, outage): keep what the last evaluation found for
                # this rule rather than silently dropping a breach and reporting the resource healthy.
                if rule.metric in previous_readings:
                    signals += 1
                    readings.append(previous_readings[rule.metric])
                if rule.metric in previous_reasons:
                    reasons.append(previous_reasons[rule.metric])
                continue
            if value is None:
                continue
            signals += 1
            severity = classify(value, rule, warning, critical)
            definition = monitor.metric(rule.metric)
            readings.append(
                {
                    "metric": rule.metric,
                    "label": definition.label if definition else rule.metric,
                    "unit": definition.unit if definition else None,
                    "value": round(value, 3),
                    "status": severity,
                    "window_minutes": rule.window_minutes,
                }
            )
            if severity != "healthy":
                reasons.append(
                    {
                        "signal": "metric",
                        "severity": severity,
                        "metric": rule.metric,
                        "label": definition.label if definition else rule.metric,
                        "unit": definition.unit if definition else None,
                        "value": round(value, 3),
                        "operator": rule.operator,
                        "threshold": critical if severity == "critical" else warning,
                        "window_minutes": rule.window_minutes,
                        "message": rule.description or (definition.label if definition else rule.metric),
                    }
                )

        if reasons:
            status = max((r["severity"] for r in reasons), key=lambda s: _RANK[s])
        elif signals:
            status = "healthy"
        else:
            status = "unknown"
        resource.health_status = status
        resource.health_reasons = reasons
        resource.health_metrics = readings
        resource.health_evaluated_at = datetime.now(UTC)
        stats["evaluated"] += 1
        stats[status] += 1
    await db.flush()
    return stats


#: Reasons a metric has no value that are not failures: it simply has no data for this resource.
_NO_DATA_REASONS = {"NO_DATA", "RELATED_RESOURCE_NOT_FOUND", "METRIC_NOT_SUPPORTED", "METRIC_NOT_FOUND"}


async def _rule_values(
    db: AsyncSession,
    azure: AzureServices,
    resources: list[Resource],
    connections: dict[uuid.UUID, AzureConnection],
    plans: dict[uuid.UUID, list[tuple[HealthRule, float | None, float | None]]],
) -> dict[tuple[uuid.UUID, str], tuple[float | None, bool]]:
    """``(value, failed)`` per (resource, metric) over each rule's window; ``failed`` means Azure errored."""
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    by_id = {r.id: r for r in resources}
    pairs = [(rid, rule) for rid, plan in plans.items() for rule, _, _ in plan]
    out: dict[tuple[uuid.UUID, str], tuple[float | None, bool]] = {}
    metrics = MetricService(db, azure)
    for window in sorted({rule.window_minutes for _, rule in pairs}):
        group = [(rid, rule) for rid, rule in pairs if rule.window_minutes == window]
        time_range = TimeRange(start=end - timedelta(minutes=window), end=end, preset="custom")
        interval = timedelta(minutes=5) if window >= 15 else timedelta(minutes=1)
        requests = [(by_id[rid], connections[by_id[rid].connection_id].tenant_id, [rule.metric]) for rid, rule in group]
        try:
            results = await metrics.get_metrics_many(requests, time_range, interval)
        except AppError:
            for rid, rule in group:
                out[(rid, rule.metric)] = (None, True)
            continue
        for (rid, rule), [data] in zip(group, results, strict=True):
            if data.unavailable_reason:
                out[(rid, rule.metric)] = (None, data.unavailable_reason not in _NO_DATA_REASONS)
                continue
            points = [p["value"] for s in data.series[:1] for p in s["points"] if p["value"] is not None]
            out[(rid, rule.metric)] = (reduce_values(points, rule.reducer), False)
    return out


async def run_health_job(organization_id: str | None = None) -> None:
    """Scheduled job: evaluate health for every organisation (or one)."""
    from app.models import Organization
    from app.services.alerts.evaluator import evaluate_alert_rules

    JOB_RUNS.inc("health")
    try:
        async with session_scope() as db:
            query = select(Organization.id).where(Organization.deleted_at.is_(None))
            if organization_id:
                query = query.where(Organization.id == uuid.UUID(organization_id))
            org_ids = list(await db.scalars(query))
        azure = get_azure_services()
        failed = 0
        for org_id in org_ids:
            # One organisation's failure (e.g. Azure unreachable for its tenant) must not stop the others.
            try:
                async with session_scope() as db:
                    await evaluate_resources(db, azure, org_id)
                async with session_scope() as db:
                    await evaluate_alert_rules(db, azure, org_id)
            except Exception:
                failed += 1
                logger.exception("health_job_org_failed", extra={"organization_id": str(org_id)})
        await get_cache().delete_prefix("amp:overview")
        if failed:
            raise RuntimeError(f"Health evaluation failed for {failed} organisation(s).")
    except Exception:
        JOB_FAILURES.inc("health")
        logger.exception("health_job_failed")
        raise
