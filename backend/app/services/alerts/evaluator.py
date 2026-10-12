"""Alert evaluation (custom rules and alert templates) and notification dispatch."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_key, get_cache
from app.models import (
    Alert,
    AlertEvent,
    AlertRule,
    AlertTemplateAssignment,
    AzureConnection,
    Environment,
    NotificationChannel,
    Project,
    Resource,
)
from app.services.alerts.channels.base import AlertNotification, ChannelNotConfiguredError
from app.services.alerts.channels.registry import get_sender
from app.services.alerts.email_lists import EMAIL_CHANNEL, resource_link, send_alert_emails
from app.services.alerts.teams_alerts import send_alert_teams
from app.services.alerts.templates import (
    TIER_RANK,
    EffectiveRule,
    active_assignments,
    alert_title,
    covering_assignment,
    load_customisations,
    monitored_resources,
    resource_rules,
    tier_for,
)
from app.services.alerts.templates import fingerprint as template_fingerprint
from app.services.azure.types import AzureServices, TimeRange
from app.services.health.evaluator import breaches
from app.services.metric_service import MetricService, reduce_values
from app.services.monitors.base import MetricDef, Rollup
from app.services.monitors.registry import get_monitor

logger = logging.getLogger(__name__)

_REDUCER: dict[str, Rollup] = {"Total": "sum", "Count": "sum", "Maximum": "max", "Minimum": "min"}
OPEN_STATUSES = ("active", "acknowledged")


def fingerprint(rule_id: uuid.UUID, resource_id: uuid.UUID) -> str:
    return f"rule:{rule_id}:{resource_id}"


async def _matching_resources(db: AsyncSession, rule: AlertRule) -> list[Resource]:
    query = select(Resource).where(
        Resource.organization_id == rule.organization_id,
        Resource.deleted_at.is_(None),
        Resource.monitor_key == rule.monitor_key,
    )
    if rule.resource_id:
        query = query.where(Resource.id == rule.resource_id)
    if rule.project_id:
        query = query.where(Resource.project_id == rule.project_id)
    if rule.environment_id:
        query = query.where(Resource.environment_id == rule.environment_id)
    return list(await db.scalars(query))


async def notify(db: AsyncSession, alert: Alert, channel_ids: list[Any], event: str, resource: Resource) -> None:
    """Tell subscriptions and the given channels (a rule's, or a template assignment's) about an alert."""
    # Email lists are organisation-wide subscriptions: they receive every alert in their scope and
    # severity, whether or not the rule names them (and are never emailed twice when it does).
    await send_alert_emails(db, alert, event, resource)
    # Subscribed Teams channels work the same way; their own settings decide, so skip them below.
    handled = await send_alert_teams(db, alert, event, resource)
    channel_ids = [cid for cid in (uuid.UUID(str(c)) for c in channel_ids) if cid not in handled]
    if not channel_ids:
        return
    channels = list(
        await db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.id.in_(channel_ids),
                NotificationChannel.organization_id == alert.organization_id,
                NotificationChannel.channel_type != EMAIL_CHANNEL,
                NotificationChannel.enabled.is_(True),
                NotificationChannel.deleted_at.is_(None),
            )
        )
    )
    if not channels:
        return
    project = await db.get(Project, resource.project_id) if resource.project_id else None
    environment = await db.get(Environment, resource.environment_id) if resource.environment_id else None
    notification = AlertNotification(
        event=event,
        alert_id=str(alert.id),
        title=alert.title,
        severity=alert.severity,
        status=alert.status,
        project=project.name if project else None,
        environment=environment.name if environment else None,
        resource_name=resource.name,
        resource_type=resource.resource_type,
        metric=alert.metric_name,
        current_value=alert.current_value,
        threshold=alert.threshold,
        started_at=alert.started_at.isoformat(),
        link=resource_link(resource.id),
    )
    for channel in channels:
        sender = get_sender(channel.channel_type)
        try:
            if sender is None:
                raise ChannelNotConfiguredError(f"Unsupported channel type {channel.channel_type}.")
            await sender.send(channel, notification)
            db.add(AlertEvent(alert_id=alert.id, event_type="notified", message=f"Sent to {channel.name}"))
        except Exception as exc:  # delivery failures must not stop evaluation
            logger.warning(
                "notification_failed", extra={"channel_type": channel.channel_type, "error_type": type(exc).__name__}
            )
            reason = str(exc) if isinstance(exc, ChannelNotConfiguredError) else "Delivery failed."
            db.add(AlertEvent(alert_id=alert.id, event_type="notification_failed", message=f"{channel.name}: {reason}"))


async def resolve_open_alerts(
    db: AsyncSession, organization_id: uuid.UUID, condition: ColumnElement[bool], message: str
) -> int:
    """Close open alerts whose condition can no longer be evaluated (rule removed, resource gone)."""
    now = datetime.now(UTC)
    alerts = list(
        await db.scalars(
            select(Alert).where(Alert.organization_id == organization_id, Alert.status.in_(OPEN_STATUSES), condition)
        )
    )
    for alert in alerts:
        alert.status = "resolved"
        alert.resolved_at = now
        db.add(AlertEvent(alert_id=alert.id, event_type="resolved", message=message))
    return len(alerts)


async def evaluate_alert_rules(
    db: AsyncSession, azure: AzureServices, organization_id: uuid.UUID, *, force: bool = False
) -> dict[str, int]:
    """Evaluate every enabled custom rule and every assigned alert template for an organisation, then notify.

    ``force`` ignores the templates' evaluation frequency (an on-demand "Evaluate now").

    Alert changes are committed before any notification is sent, so a failure part-way can never
    announce an alert that was not saved. A partial unique index on open fingerprints makes an
    overlapping evaluation skip the insert instead of creating (and announcing) a duplicate.
    """
    rules = list(
        await db.scalars(
            select(AlertRule).where(
                AlertRule.organization_id == organization_id,
                AlertRule.enabled.is_(True),
                AlertRule.deleted_at.is_(None),
            )
        )
    )
    stats = {"rules": len(rules), "fired": 0, "resolved": 0, "unchanged": 0, "no_data": 0, "closed": 0}
    tenants: dict[uuid.UUID, str] = {}
    work: list[tuple[AlertRule, MetricDef, Resource]] = []
    for rule in rules:
        definition = get_monitor(rule.monitor_key).metric(rule.metric_name)
        if definition is None:
            continue
        for resource in await _matching_resources(db, rule):
            if resource.connection_id not in tenants:
                tenants[resource.connection_id] = str(
                    await db.scalar(
                        select(AzureConnection.tenant_id).where(AzureConnection.id == resource.connection_id)
                    )
                )
            work.append((rule, definition, resource))

    values = await _window_values(db, azure, tenants, work)
    now = datetime.now(UTC)
    in_scope: set[str] = set()
    pending: list[tuple[Alert, list[Any], str, Resource]] = []
    for (rule, definition, resource), value in zip(work, values, strict=True):
        fp = fingerprint(rule.id, resource.id)
        in_scope.add(fp)
        if value is None:
            stats["no_data"] += 1
            continue
        open_alert = await db.scalar(
            select(Alert).where(
                Alert.organization_id == organization_id,
                Alert.fingerprint == fp,
                Alert.status.in_(OPEN_STATUSES),
            )
        )
        if breaches(value, rule.operator, rule.threshold):  # type: ignore[arg-type]
            if open_alert is not None:
                open_alert.current_value = round(value, 3)
                open_alert.last_evaluated_at = now
                stats["unchanged"] += 1
                continue
            alert = Alert(
                organization_id=organization_id,
                rule_id=rule.id,
                resource_id=resource.id,
                fingerprint=fp,
                severity=rule.severity,
                status="active",
                title=f"{definition.label} {_op_text(rule.operator)} {rule.threshold:g} on {resource.name}",
                metric_name=definition.label,
                current_value=round(value, 3),
                threshold=rule.threshold,
                operator=rule.operator,
                started_at=now,
                last_evaluated_at=now,
            )
            try:
                async with db.begin_nested():
                    db.add(alert)
                    await db.flush()
            except IntegrityError:
                # An overlapping evaluation opened the same alert first, and it notifies.
                stats["unchanged"] += 1
                continue
            db.add(
                AlertEvent(
                    alert_id=alert.id,
                    event_type="fired",
                    value=alert.current_value,
                    message=f"Rule '{rule.name}' fired.",
                )
            )
            pending.append((alert, list(rule.notification_channel_ids), "fired", resource))
            stats["fired"] += 1
        elif open_alert is not None:
            open_alert.status = "resolved"
            open_alert.resolved_at = now
            open_alert.current_value = round(value, 3)
            open_alert.last_evaluated_at = now
            db.add(
                AlertEvent(
                    alert_id=open_alert.id,
                    event_type="resolved",
                    value=open_alert.current_value,
                    message="Condition cleared.",
                )
            )
            pending.append((open_alert, list(rule.notification_channel_ids), "resolved", resource))
            stats["resolved"] += 1

    # Rule alerts that nothing evaluated any more: the rule was disabled or deleted, the resource was
    # removed, or it left the rule's scope. Left open, they would count as active forever.
    stale: ColumnElement[bool] = Alert.rule_id.is_not(None)
    if in_scope:
        stale = and_(stale, Alert.fingerprint.notin_(in_scope))
    stats["closed"] = await resolve_open_alerts(
        db, organization_id, stale, "Closed: the rule no longer applies to this resource."
    )
    template_stats = await _evaluate_templates(db, azure, organization_id, tenants, pending, force=force)
    stats.update(template_stats)
    await db.commit()

    for alert, channel_ids, event, resource in pending:
        await notify(db, alert, channel_ids, event, resource)
    await db.commit()
    return stats


# ---- alert templates ---------------------------------------------------------------------

#: One open alert per (resource, metric) whose severity follows the tier the value crosses.
_NOTIFY_TIERS = ("warning", "critical")


async def _evaluate_templates(
    db: AsyncSession,
    azure: AzureServices,
    organization_id: uuid.UUID,
    tenants: dict[uuid.UUID, str],
    pending: list[tuple[Alert, list[Any], str, Resource]],
    *,
    force: bool,
) -> dict[str, int]:
    stats = {
        "template_rules": 0,
        "template_fired": 0,
        "template_escalated": 0,
        "template_deescalated": 0,
        "template_resolved": 0,
        "template_unchanged": 0,
        "template_skipped": 0,
        "template_no_data": 0,
        "template_closed": 0,
    }
    assignments = await active_assignments(db, organization_id)
    customisations = await load_customisations(db, organization_id)
    cache = get_cache()
    covered: set[str] = set()
    work: list[tuple[Resource, EffectiveRule, AlertTemplateAssignment]] = []
    for resource in await monitored_resources(db, organization_id) if assignments else []:
        assignment = covering_assignment(resource, assignments)
        if assignment is None:
            continue
        for rule in resource_rules(resource, customisations, assignment):
            if not rule.enabled:
                continue
            covered.add(template_fingerprint(resource.id, rule.metric))
            stats["template_rules"] += 1
            if not force and await cache.get(_due_key(resource.id, rule.metric)):
                stats["template_skipped"] += 1
                continue
            if resource.connection_id not in tenants:
                tenants[resource.connection_id] = str(
                    await db.scalar(
                        select(AzureConnection.tenant_id).where(AzureConnection.id == resource.connection_id)
                    )
                )
            work.append((resource, rule, assignment))

    values = await _template_values(db, azure, tenants, work)
    now = datetime.now(UTC)
    for (resource, rule, assignment), value in zip(work, values, strict=True):
        # Next evaluation after the rule's frequency (a little early, so a 5-minute job never skips).
        await cache.set(_due_key(resource.id, rule.metric), 1, max(rule.frequency_minutes * 60 - 30, 30))
        if value is None:
            stats["template_no_data"] += 1  # unreadable: leave any open alert as it is
            continue
        fp = template_fingerprint(resource.id, rule.metric)
        open_alert = await db.scalar(
            select(Alert).where(
                Alert.organization_id == organization_id, Alert.fingerprint == fp, Alert.status.in_(OPEN_STATUSES)
            )
        )
        tier = tier_for(value, rule)
        current = round(value, 3)
        channels = list(assignment.notification_channel_ids or [])
        if tier is None:
            if open_alert is None:
                stats["template_unchanged"] += 1
                continue
            previous = open_alert.severity
            open_alert.status, open_alert.resolved_at = "resolved", now
            open_alert.current_value, open_alert.last_evaluated_at = current, now
            db.add(
                AlertEvent(
                    alert_id=open_alert.id,
                    event_type="resolved",
                    value=current,
                    message="Back below the informational threshold.",
                )
            )
            if previous in _NOTIFY_TIERS:
                pending.append((open_alert, channels, "resolved", resource))
            stats["template_resolved"] += 1
            continue
        threshold = rule.threshold(tier)
        if open_alert is None:
            alert = Alert(
                organization_id=organization_id,
                rule_id=None,
                resource_id=resource.id,
                fingerprint=fp,
                source="template",
                severity=tier,
                status="active",
                title=alert_title(rule, tier, resource.name),
                metric_name=rule.label,
                current_value=current,
                threshold=threshold,
                operator=rule.operator,
                started_at=now,
                last_evaluated_at=now,
            )
            try:
                async with db.begin_nested():
                    db.add(alert)
                    await db.flush()
            except IntegrityError:
                stats["template_unchanged"] += 1  # an overlapping evaluation opened it first
                continue
            db.add(
                AlertEvent(
                    alert_id=alert.id,
                    event_type="fired",
                    value=current,
                    message=f"{tier.capitalize()} threshold crossed.",
                )
            )
            if tier in _NOTIFY_TIERS:
                pending.append((alert, channels, "fired", resource))
            stats["template_fired"] += 1
            continue
        previous = open_alert.severity
        open_alert.current_value, open_alert.last_evaluated_at = current, now
        if tier == previous:
            stats["template_unchanged"] += 1
            continue
        open_alert.severity, open_alert.threshold = tier, threshold
        open_alert.title = alert_title(rule, tier, resource.name)
        if TIER_RANK[tier] > TIER_RANK.get(previous, 0):
            db.add(
                AlertEvent(
                    alert_id=open_alert.id,
                    event_type="escalated",
                    value=current,
                    message=f"Escalated from {previous} to {tier}.",
                )
            )
            if tier in _NOTIFY_TIERS:
                pending.append((open_alert, channels, "fired", resource))
            stats["template_escalated"] += 1
        else:
            db.add(
                AlertEvent(
                    alert_id=open_alert.id,
                    event_type="de-escalated",
                    value=current,
                    message=f"Eased from {previous} to {tier}.",
                )
            )
            stats["template_deescalated"] += 1

    # Template alerts nothing covers any more (assignment removed or disabled, rule disabled,
    # resource deleted) are closed, not left open forever.
    stale: ColumnElement[bool] = and_(Alert.source == "template", Alert.rule_id.is_(None))
    if covered:
        stale = and_(stale, Alert.fingerprint.notin_(covered))
    stats["template_closed"] = await resolve_open_alerts(
        db, organization_id, stale, "Closed: no alert template covers this resource and metric any more."
    )
    return stats


def _due_key(resource_id: uuid.UUID, metric: str) -> str:
    return cache_key("template_due", str(resource_id), metric)


async def _template_values(
    db: AsyncSession,
    azure: AzureServices,
    tenants: dict[uuid.UUID, str],
    work: list[tuple[Resource, EffectiveRule, AlertTemplateAssignment]],
) -> list[float | None]:
    """Each template rule's window value per resource (``None`` when unreadable), batched per window."""
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    values: list[float | None] = [None] * len(work)
    metrics = MetricService(db, azure)
    for window in sorted({rule.window_minutes for _, rule, _ in work}):
        indexes = [i for i, (_, rule, _) in enumerate(work) if rule.window_minutes == window]
        time_range = TimeRange(start=end - timedelta(minutes=window), end=end, preset="custom")
        interval = timedelta(minutes=5) if window >= 15 else timedelta(minutes=1)
        requests = [(work[i][0], tenants[work[i][0].connection_id], [work[i][1].metric]) for i in indexes]
        results = await metrics.get_metrics_many(requests, time_range, interval)
        for i, [data] in zip(indexes, results, strict=True):
            if data.unavailable_reason:
                continue
            points = [p["value"] for s in data.series[:1] for p in s["points"] if p["value"] is not None]
            values[i] = reduce_values(points, work[i][1].reducer)  # type: ignore[arg-type]
    return values


async def resolve_uncovered_template_alerts(db: AsyncSession, organization_id: uuid.UUID) -> int:
    """Close open template alerts of resources no enabled assignment covers (after delete/disable)."""
    assignments = await active_assignments(db, organization_id)
    open_alerts = list(
        await db.scalars(
            select(Alert).where(
                Alert.organization_id == organization_id,
                Alert.source == "template",
                Alert.status.in_(OPEN_STATUSES),
            )
        )
    )
    if not open_alerts:
        return 0
    resources = {
        r.id: r for r in await db.scalars(select(Resource).where(Resource.id.in_({a.resource_id for a in open_alerts})))
    }
    uncovered = [
        a.id
        for a in open_alerts
        if (r := resources.get(a.resource_id)) is None or covering_assignment(r, assignments) is None
    ]
    if not uncovered:
        return 0
    return await resolve_open_alerts(
        db, organization_id, Alert.id.in_(uncovered), "Closed: no alert template covers this resource any more."
    )


async def _window_values(
    db: AsyncSession,
    azure: AzureServices,
    tenants: dict[uuid.UUID, str],
    work: list[tuple[AlertRule, MetricDef, Resource]],
) -> list[float | None]:
    """Each rule's window value per resource (``None`` when unreadable), read concurrently per window."""
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    values: list[float | None] = [None] * len(work)
    metrics = MetricService(db, azure)
    for window in sorted({rule.window_minutes for rule, _, _ in work}):
        indexes = [i for i, (rule, _, _) in enumerate(work) if rule.window_minutes == window]
        time_range = TimeRange(start=end - timedelta(minutes=window), end=end, preset="custom")
        interval = timedelta(minutes=5) if window >= 15 else timedelta(minutes=1)
        requests = [(work[i][2], tenants[work[i][2].connection_id], [work[i][0].metric_name]) for i in indexes]
        results = await metrics.get_metrics_many(requests, time_range, interval)
        for i, [data] in zip(indexes, results, strict=True):
            if data.unavailable_reason:
                continue
            points = [p["value"] for s in data.series[:1] for p in s["points"] if p["value"] is not None]
            values[i] = reduce_values(points, _REDUCER.get(work[i][0].aggregation, "avg"))
    return values


def _op_text(operator: str) -> str:
    return {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}.get(operator, operator)
