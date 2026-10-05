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
from datetime import UTC, datetime
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
from app.services.azure.types import AzureServices
from app.services.metric_service import MetricService
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

    metrics = MetricService(db, azure)
    stats = {"evaluated": 0, "healthy": 0, "warning": 0, "critical": 0, "unknown": 0}
    for resource in resources:
        connection = connections[resource.connection_id]
        monitor = get_monitor(resource.monitor_key)
        reasons: list[dict[str, Any]] = []
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

        for rule in monitor.health_rules:
            override = overrides.get((monitor.key, rule.metric))
            if override is not None and not override.enabled:
                continue
            warning = override.warning_threshold if override else rule.warning
            critical = override.critical_threshold if override else rule.critical
            try:
                value, unavailable = await metrics.window_value(
                    resource, connection.tenant_id, rule.metric, rule.window_minutes, rule.reducer
                )
            except AppError:
                continue
            if unavailable or value is None:
                continue
            signals += 1
            severity = classify(value, rule, warning, critical)
            if severity != "healthy":
                definition = monitor.metric(rule.metric)
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
        resource.health_evaluated_at = datetime.now(UTC)
        stats["evaluated"] += 1
        stats[status] += 1
    await db.flush()
    return stats


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
        for org_id in org_ids:
            async with session_scope() as db:
                await evaluate_resources(db, azure, org_id)
            async with session_scope() as db:
                await evaluate_alert_rules(db, azure, org_id)
        await get_cache().delete_prefix("amp:overview")
    except Exception:
        JOB_FAILURES.inc("health")
        logger.exception("health_job_failed")
        raise
