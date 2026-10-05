from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession, require
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.permissions import Permission
from app.models import (
    Alert,
    AlertEvent,
    AlertRule,
    Environment,
    HealthThreshold,
    NotificationChannel,
    Project,
    Resource,
)
from app.schemas.alerts import (
    AlertDetail,
    AlertEventOut,
    AlertOut,
    AlertRuleIn,
    AlertRuleOut,
    ChannelIn,
    ChannelOut,
    HealthRuleOut,
    HealthThresholdIn,
)
from app.schemas.common import Page
from app.services.alerts.channels.base import AlertNotification
from app.services.alerts.channels.registry import get_sender
from app.services.audit import record_audit
from app.services.monitors.registry import all_monitors, get_monitor
from app.services.views import alert_views

router = APIRouter(tags=["alerts"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_alerts))]
Acker = Annotated[CurrentUser, Depends(require(Permission.acknowledge_alerts))]
Manager = Annotated[CurrentUser, Depends(require(Permission.manage_alerts))]


# ---- alerts ---------------------------------------------------------------------------


@router.get("/alerts", response_model=Page[AlertOut])
async def list_alerts(
    db: DbSession,
    user: Viewer,
    status_filter: Annotated[
        str | None, Query(alias="status", pattern=r"^(active|acknowledged|resolved|open)$")
    ] = None,
    severity: Annotated[str | None, Query(pattern=r"^(critical|warning|info)$")] = None,
    project_id: uuid.UUID | None = None,
    environment_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Alert title or resource name")] = None,
    monitor_key: Annotated[str | None, Query(max_length=60, description="Resource type (monitor key)")] = None,
    since_hours: Annotated[int | None, Query(ge=1, le=24 * 90, description="Started within the last N hours")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[AlertOut]:
    query = (
        select(Alert)
        .join(Resource, Resource.id == Alert.resource_id)
        .where(Alert.organization_id == user.organization_id)
    )
    if status_filter == "open":
        query = query.where(Alert.status.in_(["active", "acknowledged"]))
    elif status_filter:
        query = query.where(Alert.status == status_filter)
    if severity:
        query = query.where(Alert.severity == severity)
    if project_id:
        query = query.where(Resource.project_id == project_id)
    if environment_id:
        query = query.where(Resource.environment_id == environment_id)
    if resource_id:
        query = query.where(Alert.resource_id == resource_id)
    if monitor_key:
        query = query.where(Resource.monitor_key == monitor_key)
    if since_hours:
        query = query.where(Alert.started_at >= datetime.now(UTC) - timedelta(hours=since_hours))
    if q and q.strip():
        term = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        query = query.where(
            or_(func.lower(Alert.title).like(term, escape="\\"), func.lower(Resource.name).like(term, escape="\\"))
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    alerts = list(
        await db.scalars(query.order_by(Alert.started_at.desc()).offset((page - 1) * page_size).limit(page_size))
    )
    return Page(items=await alert_views(db, alerts), total=int(total or 0), page=page, page_size=page_size)


async def _alert(db: DbSession, user: CurrentUser, alert_id: uuid.UUID) -> Alert:
    alert = await db.scalar(select(Alert).where(Alert.id == alert_id, Alert.organization_id == user.organization_id))
    if alert is None:
        raise NotFoundError("Alert not found.")
    return alert


async def _detail(db: DbSession, alert: Alert) -> AlertDetail:
    [view] = await alert_views(db, [alert])
    events = list(
        await db.scalars(
            select(AlertEvent).where(AlertEvent.alert_id == alert.id).order_by(AlertEvent.created_at.desc())
        )
    )
    return AlertDetail(**view.model_dump(), events=[AlertEventOut.model_validate(e) for e in events])


@router.get("/alerts/{alert_id}", response_model=AlertDetail)
async def get_alert(alert_id: uuid.UUID, db: DbSession, user: Viewer) -> AlertDetail:
    return await _detail(db, await _alert(db, user, alert_id))


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertDetail)
async def acknowledge_alert(alert_id: uuid.UUID, request: Request, db: DbSession, user: Acker) -> AlertDetail:
    alert = await _alert(db, user, alert_id)
    if alert.status != "active":
        raise ConflictError("Only active alerts can be acknowledged.")
    alert.status, alert.acknowledged_at, alert.acknowledged_by_id = "acknowledged", datetime.now(UTC), user.id
    db.add(
        AlertEvent(
            alert_id=alert.id,
            event_type="acknowledged",
            actor_user_id=user.id,
            message=f"Acknowledged by {user.display_name or user.email or 'user'}",
        )
    )
    await record_audit(
        db, action="alert.acknowledged", user=user, target_type="alert", target_id=str(alert.id), request=request
    )
    await db.commit()
    return await _detail(db, alert)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertDetail)
async def resolve_alert(alert_id: uuid.UUID, request: Request, db: DbSession, user: Acker) -> AlertDetail:
    alert = await _alert(db, user, alert_id)
    if alert.status == "resolved":
        raise ConflictError("The alert is already resolved.")
    alert.status, alert.resolved_at = "resolved", datetime.now(UTC)
    db.add(
        AlertEvent(
            alert_id=alert.id,
            event_type="resolved",
            actor_user_id=user.id,
            message=f"Resolved manually by {user.display_name or user.email or 'user'}",
        )
    )
    await record_audit(
        db, action="alert.resolved", user=user, target_type="alert", target_id=str(alert.id), request=request
    )
    await db.commit()
    return await _detail(db, alert)


# ---- rules ----------------------------------------------------------------------------


async def _validate_rule(db: DbSession, user: CurrentUser, body: AlertRuleIn) -> None:
    monitor = get_monitor(body.monitor_key)
    if monitor.key != body.monitor_key or monitor.metric(body.metric_name) is None:
        raise ValidationFailedError("Unknown resource type or metric.")
    if body.resource_id:
        r = await db.scalar(
            select(Resource.id).where(Resource.id == body.resource_id, Resource.organization_id == user.organization_id)
        )
        if r is None:
            raise ValidationFailedError("Resource not found.")
    if body.project_id:
        p = await db.scalar(
            select(Project.id).where(Project.id == body.project_id, Project.organization_id == user.organization_id)
        )
        if p is None:
            raise ValidationFailedError("Project not found.")
    if body.environment_id:
        e = await db.scalar(
            select(Environment.id).where(
                Environment.id == body.environment_id, Environment.organization_id == user.organization_id
            )
        )
        if e is None:
            raise ValidationFailedError("Environment not found.")
    if body.notification_channel_ids:
        found = await db.scalar(
            select(func.count(NotificationChannel.id)).where(
                NotificationChannel.id.in_(body.notification_channel_ids),
                NotificationChannel.organization_id == user.organization_id,
                NotificationChannel.deleted_at.is_(None),
            )
        )
        if found != len(set(body.notification_channel_ids)):
            raise ValidationFailedError("One or more notification channels were not found.")


def _rule_values(body: AlertRuleIn) -> dict[str, object]:
    values = body.model_dump()
    values["notification_channel_ids"] = [str(c) for c in body.notification_channel_ids]
    return values


@router.get("/alert-rules", response_model=list[AlertRuleOut])
async def list_rules(db: DbSession, user: Viewer) -> list[AlertRule]:
    return list(
        await db.scalars(
            select(AlertRule)
            .where(AlertRule.organization_id == user.organization_id, AlertRule.deleted_at.is_(None))
            .order_by(AlertRule.name)
        )
    )


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(body: AlertRuleIn, request: Request, db: DbSession, user: Manager) -> AlertRule:
    await _validate_rule(db, user, body)
    rule = AlertRule(organization_id=user.organization_id, created_by_id=user.id, **_rule_values(body))
    db.add(rule)
    await db.flush()
    await record_audit(
        db,
        action="alert_rule.created",
        user=user,
        target_type="alert_rule",
        target_id=str(rule.id),
        request=request,
        details=body.model_dump(mode="json"),
    )
    await db.commit()
    return rule


async def _rule(db: DbSession, user: CurrentUser, rule_id: uuid.UUID) -> AlertRule:
    rule = await db.scalar(
        select(AlertRule).where(
            AlertRule.id == rule_id, AlertRule.organization_id == user.organization_id, AlertRule.deleted_at.is_(None)
        )
    )
    if rule is None:
        raise NotFoundError("Alert rule not found.")
    return rule


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: uuid.UUID, body: AlertRuleIn, request: Request, db: DbSession, user: Manager
) -> AlertRule:
    rule = await _rule(db, user, rule_id)
    await _validate_rule(db, user, body)
    for field, value in _rule_values(body).items():
        setattr(rule, field, value)
    await record_audit(
        db,
        action="alert_rule.changed",
        user=user,
        target_type="alert_rule",
        target_id=str(rule.id),
        request=request,
        details=body.model_dump(mode="json"),
    )
    await db.commit()
    return rule


@router.delete("/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_rule(rule_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> None:
    rule = await _rule(db, user, rule_id)
    rule.deleted_at = datetime.now(UTC)
    rule.enabled = False
    await record_audit(
        db,
        action="alert_rule.deleted",
        user=user,
        target_type="alert_rule",
        target_id=str(rule.id),
        request=request,
        details={"name": rule.name},
    )
    await db.commit()


# ---- notification channels ------------------------------------------------------------


@router.get("/notification-channels", response_model=list[ChannelOut])
async def list_channels(db: DbSession, user: Manager) -> list[NotificationChannel]:
    return list(
        await db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.organization_id == user.organization_id, NotificationChannel.deleted_at.is_(None)
            )
        )
    )


@router.post("/notification-channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(body: ChannelIn, request: Request, db: DbSession, user: Manager) -> NotificationChannel:
    sender = get_sender(body.channel_type)
    if sender and sender.requires_secret and not body.secret_ref:
        raise ValidationFailedError("This channel type requires a Key Vault secret reference.")
    for value in body.config.values():
        for item in value if isinstance(value, list) else [value]:
            if "://" in item:
                raise ValidationFailedError("Endpoint URLs must be stored in Key Vault, not in channel settings.")
    channel = NotificationChannel(organization_id=user.organization_id, **body.model_dump())
    db.add(channel)
    await db.flush()
    await record_audit(
        db,
        action="notification_channel.created",
        user=user,
        target_type="notification_channel",
        target_id=str(channel.id),
        request=request,
        details={"name": body.name, "type": body.channel_type},
    )
    await db.commit()
    return channel


@router.delete("/notification-channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_channel(channel_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> None:
    channel = await db.scalar(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.organization_id == user.organization_id,
            NotificationChannel.deleted_at.is_(None),
        )
    )
    if channel is None:
        raise NotFoundError("Notification channel not found.")
    channel.deleted_at = datetime.now(UTC)
    await record_audit(
        db,
        action="notification_channel.deleted",
        user=user,
        target_type="notification_channel",
        target_id=str(channel.id),
        request=request,
    )
    await db.commit()


@router.post("/notification-channels/{channel_id}/test", response_model=dict[str, str])
async def test_channel(channel_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> dict[str, str]:
    channel = await db.scalar(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.organization_id == user.organization_id,
            NotificationChannel.deleted_at.is_(None),
        )
    )
    if channel is None:
        raise NotFoundError("Notification channel not found.")
    sender = get_sender(channel.channel_type)
    notification = AlertNotification(
        event="test",
        alert_id="test",
        title="Test notification from the Azure Monitoring Platform",
        severity="info",
        status="test",
        project=None,
        environment=None,
        resource_name="n/a",
        resource_type="n/a",
        metric=None,
        current_value=None,
        threshold=None,
        started_at=datetime.now(UTC).isoformat(),
        link=None,
    )
    try:
        if sender is None:
            raise ValueError("Unsupported channel type.")
        await sender.send(channel, notification)
        outcome = {"status": "sent", "message": "Test notification sent."}
    except Exception as exc:
        from app.services.alerts.channels.base import ChannelNotConfiguredError

        message = str(exc) if isinstance(exc, ChannelNotConfiguredError) else "Delivery failed."
        outcome = {"status": "failed", "message": message}
    await record_audit(
        db,
        action="notification_channel.tested",
        user=user,
        target_type="notification_channel",
        target_id=str(channel.id),
        request=request,
        result="success" if outcome["status"] == "sent" else "failure",
    )
    await db.commit()
    return outcome


# ---- health thresholds ----------------------------------------------------------------


@router.get("/health-rules", response_model=list[HealthRuleOut])
async def list_health_rules(db: DbSession, user: Viewer) -> list[HealthRuleOut]:
    overrides = {
        (t.monitor_key, t.metric_name): t
        for t in await db.scalars(
            select(HealthThreshold).where(HealthThreshold.organization_id == user.organization_id)
        )
    }
    out = []
    for monitor in all_monitors():
        for rule in monitor.health_rules:
            definition = monitor.metric(rule.metric)
            o = overrides.get((monitor.key, rule.metric))
            out.append(
                HealthRuleOut(
                    monitor_key=monitor.key,
                    monitor_name=monitor.display_name,
                    metric_name=rule.metric,
                    metric_label=definition.label if definition else rule.metric,
                    unit=definition.unit if definition else "",
                    operator=rule.operator,
                    window_minutes=rule.window_minutes,
                    default_warning=rule.warning,
                    default_critical=rule.critical,
                    warning_threshold=o.warning_threshold if o else rule.warning,
                    critical_threshold=o.critical_threshold if o else rule.critical,
                    enabled=o.enabled if o else True,
                    overridden=o is not None,
                )
            )
    return out


@router.put("/health-rules", response_model=HealthRuleOut)
async def set_health_threshold(
    body: HealthThresholdIn,
    request: Request,
    db: DbSession,
    user: Annotated[CurrentUser, Depends(require(Permission.manage_settings))],
) -> HealthRuleOut:
    monitor = get_monitor(body.monitor_key)
    rule = next((r for r in monitor.health_rules if r.metric == body.metric_name), None)
    if monitor.key != body.monitor_key or rule is None:
        raise ValidationFailedError("Unknown health rule.")
    row = await db.scalar(
        select(HealthThreshold).where(
            HealthThreshold.organization_id == user.organization_id,
            HealthThreshold.monitor_key == body.monitor_key,
            HealthThreshold.metric_name == body.metric_name,
        )
    )
    if row is None:
        row = HealthThreshold(
            organization_id=user.organization_id, monitor_key=body.monitor_key, metric_name=body.metric_name
        )
        db.add(row)
    row.warning_threshold, row.critical_threshold, row.enabled = (
        body.warning_threshold,
        body.critical_threshold,
        body.enabled,
    )
    await record_audit(
        db,
        action="health_threshold.changed",
        user=user,
        target_type="health_threshold",
        target_id=f"{body.monitor_key}.{body.metric_name}",
        request=request,
        details=body.model_dump(),
    )
    await db.commit()
    definition = monitor.metric(rule.metric)
    return HealthRuleOut(
        monitor_key=monitor.key,
        monitor_name=monitor.display_name,
        metric_name=rule.metric,
        metric_label=definition.label if definition else rule.metric,
        unit=definition.unit if definition else "",
        operator=rule.operator,
        window_minutes=rule.window_minutes,
        default_warning=rule.warning,
        default_critical=rule.critical,
        warning_threshold=row.warning_threshold,
        critical_threshold=row.critical_threshold,
        enabled=row.enabled,
        overridden=True,
    )
