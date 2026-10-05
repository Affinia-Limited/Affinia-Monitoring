"""Alert rule evaluation and notification dispatch."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import (
    Alert,
    AlertEvent,
    AlertRule,
    AzureConnection,
    Environment,
    NotificationChannel,
    Project,
    Resource,
)
from app.services.alerts.channels.base import AlertNotification, ChannelNotConfiguredError
from app.services.alerts.channels.registry import get_sender
from app.services.azure.types import AzureServices
from app.services.health.evaluator import breaches
from app.services.metric_service import MetricService
from app.services.monitors.base import Rollup
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


async def notify(db: AsyncSession, alert: Alert, rule: AlertRule | None, event: str, resource: Resource) -> None:
    channel_ids = [uuid.UUID(str(c)) for c in (rule.notification_channel_ids if rule else [])]
    if not channel_ids:
        return
    channels = list(
        await db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.id.in_(channel_ids),
                NotificationChannel.organization_id == alert.organization_id,
                NotificationChannel.enabled.is_(True),
                NotificationChannel.deleted_at.is_(None),
            )
        )
    )
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
        link=None,
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


async def evaluate_alert_rules(db: AsyncSession, azure: AzureServices, organization_id: uuid.UUID) -> dict[str, int]:
    rules = list(
        await db.scalars(
            select(AlertRule).where(
                AlertRule.organization_id == organization_id,
                AlertRule.enabled.is_(True),
                AlertRule.deleted_at.is_(None),
            )
        )
    )
    stats = {"rules": len(rules), "fired": 0, "resolved": 0, "unchanged": 0, "no_data": 0}
    metrics = MetricService(db, azure)
    tenants: dict[uuid.UUID, str] = {}
    now = datetime.now(UTC)
    for rule in rules:
        monitor = get_monitor(rule.monitor_key)
        definition = monitor.metric(rule.metric_name)
        if definition is None:
            continue
        for resource in await _matching_resources(db, rule):
            if resource.connection_id not in tenants:
                tenants[resource.connection_id] = str(
                    await db.scalar(
                        select(AzureConnection.tenant_id).where(AzureConnection.id == resource.connection_id)
                    )
                )
            try:
                value, unavailable = await metrics.window_value(
                    resource,
                    tenants[resource.connection_id],
                    rule.metric_name,
                    rule.window_minutes,
                    _REDUCER.get(rule.aggregation, "avg"),
                )
            except AppError:
                value, unavailable = None, "ERROR"
            fp = fingerprint(rule.id, resource.id)
            open_alert = await db.scalar(
                select(Alert).where(
                    Alert.organization_id == organization_id,
                    Alert.fingerprint == fp,
                    Alert.status.in_(OPEN_STATUSES),
                )
            )
            if unavailable or value is None:
                stats["no_data"] += 1
                continue
            if breaches(value, rule.operator, rule.threshold):  # type: ignore[arg-type]
                if open_alert is None:
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
                    db.add(alert)
                    await db.flush()
                    db.add(
                        AlertEvent(
                            alert_id=alert.id,
                            event_type="fired",
                            value=alert.current_value,
                            message=f"Rule '{rule.name}' fired.",
                        )
                    )
                    await notify(db, alert, rule, "fired", resource)
                    stats["fired"] += 1
                else:
                    open_alert.current_value = round(value, 3)
                    open_alert.last_evaluated_at = now
                    stats["unchanged"] += 1
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
                await notify(db, open_alert, rule, "resolved", resource)
                stats["resolved"] += 1
    await db.flush()
    return stats


def _op_text(operator: str) -> str:
    return {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}.get(operator, operator)
