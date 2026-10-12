from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession, require
from app.core.config import Environment as AppEnvironment
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.permissions import Permission
from app.models import (
    Alert,
    AlertEvent,
    AlertRule,
    Environment,
    HealthThreshold,
    NotificationChannel,
    Organization,
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
    EmailListIn,
    EmailListOut,
    EmailListUpdate,
    EmailStatusOut,
    HealthRuleOut,
    HealthThresholdIn,
    TeamsChannelIn,
    TeamsChannelOut,
    TeamsChannelUpdate,
    TeamsSetupOut,
)
from app.schemas.common import Page
from app.services.alerts.channels.base import AlertNotification
from app.services.alerts.channels.registry import get_sender
from app.services.alerts.email_lists import EMAIL_CHANNEL, EmailList, send_test_email
from app.services.alerts.evaluator import resolve_open_alerts
from app.services.alerts.teams_alerts import (
    TEAMS_CHANNEL,
    TeamsSubscription,
    is_teams_subscription,
    teams_config,
)
from app.services.audit import record_audit
from app.services.email import email_status, mask_all
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
        # Alerts fired in one evaluation share started_at; id keeps OFFSET pages stable.
        await db.scalars(
            query.order_by(Alert.started_at.desc(), Alert.id).offset((page - 1) * page_size).limit(page_size)
        )
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
            select(Resource.id).where(
                Resource.id == body.resource_id,
                Resource.organization_id == user.organization_id,
                Resource.deleted_at.is_(None),
            )
        )
        if r is None:
            raise ValidationFailedError("Resource not found.")
    if body.project_id:
        p = await db.scalar(
            select(Project.id).where(
                Project.id == body.project_id,
                Project.organization_id == user.organization_id,
                Project.deleted_at.is_(None),
            )
        )
        if p is None:
            raise ValidationFailedError("Project not found.")
    if body.environment_id:
        e = await db.scalar(
            select(Environment).where(
                Environment.id == body.environment_id,
                Environment.organization_id == user.organization_id,
                Environment.deleted_at.is_(None),
            )
        )
        if e is None:
            raise ValidationFailedError("Environment not found.")
        if body.project_id and e.project_id != body.project_id:
            raise ValidationFailedError("The environment must belong to the selected project.")
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
    if not rule.enabled:
        await resolve_open_alerts(db, user.organization_id, Alert.rule_id == rule.id, "Closed: the rule was disabled.")
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
    await resolve_open_alerts(db, user.organization_id, Alert.rule_id == rule.id, "Closed: the rule was deleted.")
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
                NotificationChannel.organization_id == user.organization_id,
                NotificationChannel.deleted_at.is_(None),
                # Email lists have their own endpoints (and their recipients their own access rules).
                NotificationChannel.channel_type != EMAIL_CHANNEL,
            )
        )
    )


async def _secret_prefix(db: DbSession, user: CurrentUser) -> str:
    slug = await db.scalar(select(Organization.slug).where(Organization.id == user.organization_id))
    return f"{slug}-"


async def _check_secret_ref(db: DbSession, user: CurrentUser, secret_ref: str) -> None:
    """Key Vault is shared by every organisation: a channel may only use this organisation's secrets."""
    prefix = await _secret_prefix(db, user)
    if not secret_ref.lower().startswith(prefix):
        raise ValidationFailedError(
            f"The Key Vault secret name must start with your organisation's prefix '{prefix}' "
            f"(for example '{prefix}teams-ops')."
        )


@router.post("/notification-channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(body: ChannelIn, request: Request, db: DbSession, user: Manager) -> NotificationChannel:
    if body.channel_type == EMAIL_CHANNEL:
        raise ValidationFailedError("Create email notifications as an email list (Alerts > Email notifications).")
    sender = get_sender(body.channel_type)
    if sender and sender.requires_secret and not body.secret_ref:
        raise ValidationFailedError("This channel type requires a Key Vault secret reference.")
    if body.secret_ref:
        await _check_secret_ref(db, user, body.secret_ref)
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
            NotificationChannel.channel_type != EMAIL_CHANNEL,
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

        # One message for every delivery problem, so the test cannot be used to probe Key Vault.
        message = (
            str(exc)
            if isinstance(exc, ChannelNotConfiguredError)
            else "Delivery failed. Check that the Key Vault secret exists and holds the endpoint's public "
            "https:// URL, and that the endpoint accepts the request."
        )
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


# ---- email lists -------------------------------------------------------------------------
#
# Recipients are personal data: only alerts:manage can read them, and audit entries and logs carry
# masked addresses only (a***@contoso.com).


@router.get("/notifications/email-status", response_model=EmailStatusOut)
async def get_email_status(user: Viewer) -> dict[str, object]:
    """Whether this deployment can send email (no endpoints or addresses)."""
    return email_status()


async def _email_list(db: DbSession, user: CurrentUser, list_id: uuid.UUID) -> NotificationChannel:
    channel = await db.scalar(
        select(NotificationChannel).where(
            NotificationChannel.id == list_id,
            NotificationChannel.organization_id == user.organization_id,
            NotificationChannel.channel_type == EMAIL_CHANNEL,
            NotificationChannel.deleted_at.is_(None),
        )
    )
    if channel is None:
        raise NotFoundError("Email list not found.")
    return channel


async def _validate_email_scope(
    db: DbSession, user: CurrentUser, project_id: uuid.UUID | None, environment_id: uuid.UUID | None
) -> None:
    if environment_id and not project_id:
        raise ValidationFailedError("Choose the project of the environment.")
    if project_id:
        found = await db.scalar(
            select(Project.id).where(
                Project.id == project_id, Project.organization_id == user.organization_id, Project.deleted_at.is_(None)
            )
        )
        if found is None:
            raise ValidationFailedError("The project was not found.")
    if environment_id:
        env = await db.scalar(
            select(Environment).where(
                Environment.id == environment_id,
                Environment.organization_id == user.organization_id,
                Environment.deleted_at.is_(None),
            )
        )
        if env is None or env.project_id != project_id:
            raise ValidationFailedError("The environment must belong to the chosen project.")


async def _email_list_views(db: DbSession, channels: list[NotificationChannel]) -> list[EmailListOut]:
    lists = [(c, EmailList.from_channel(c)) for c in channels]
    project_ids = {lst.project_id for _, lst in lists if lst.project_id}
    env_ids = {lst.environment_id for _, lst in lists if lst.environment_id}
    projects = (
        {p.id: p.name for p in await db.scalars(select(Project).where(Project.id.in_(project_ids)))}
        if project_ids
        else {}
    )
    envs = (
        {e.id: e.name for e in await db.scalars(select(Environment).where(Environment.id.in_(env_ids)))}
        if env_ids
        else {}
    )
    return [
        EmailListOut(
            id=c.id,
            name=c.name,
            enabled=c.enabled,
            recipients=list(lst.recipients),
            min_severity="warning" if lst.min_severity == "warning" else "critical",
            notify_resolved=lst.notify_resolved,
            project_id=lst.project_id,
            environment_id=lst.environment_id,
            project_name=projects.get(lst.project_id) if lst.project_id else None,
            environment_name=envs.get(lst.environment_id) if lst.environment_id else None,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c, lst in lists
    ]


def _email_config(
    recipients: list[str],
    min_severity: str,
    notify_resolved: bool,
    project_id: uuid.UUID | None,
    environment_id: uuid.UUID | None,
) -> dict[str, object]:
    return {
        "recipients": recipients,
        "min_severity": min_severity,
        "notify_resolved": notify_resolved,
        "project_id": str(project_id) if project_id else None,
        "environment_id": str(environment_id) if environment_id else None,
    }


def _audit_details(channel: NotificationChannel) -> dict[str, object]:
    lst = EmailList.from_channel(channel)
    return {
        "name": channel.name,
        "recipients": mask_all(lst.recipients),
        "min_severity": lst.min_severity,
        "notify_resolved": lst.notify_resolved,
        "enabled": channel.enabled,
        "project_id": str(lst.project_id) if lst.project_id else None,
        "environment_id": str(lst.environment_id) if lst.environment_id else None,
    }


@router.get("/notifications/email-lists", response_model=list[EmailListOut])
async def list_email_lists(db: DbSession, user: Manager) -> list[EmailListOut]:
    channels = list(
        await db.scalars(
            select(NotificationChannel)
            .where(
                NotificationChannel.organization_id == user.organization_id,
                NotificationChannel.channel_type == EMAIL_CHANNEL,
                NotificationChannel.deleted_at.is_(None),
            )
            .order_by(NotificationChannel.name)
        )
    )
    return await _email_list_views(db, channels)


@router.post("/notifications/email-lists", response_model=EmailListOut, status_code=status.HTTP_201_CREATED)
async def create_email_list(body: EmailListIn, request: Request, db: DbSession, user: Manager) -> EmailListOut:
    await _validate_email_scope(db, user, body.project_id, body.environment_id)
    channel = NotificationChannel(
        organization_id=user.organization_id,
        name=body.name,
        channel_type=EMAIL_CHANNEL,
        enabled=body.enabled,
        config=_email_config(
            body.recipients, body.min_severity, body.notify_resolved, body.project_id, body.environment_id
        ),
    )
    db.add(channel)
    await db.flush()
    await record_audit(
        db,
        action="email_list.created",
        user=user,
        target_type="email_list",
        target_id=str(channel.id),
        request=request,
        details=_audit_details(channel),
    )
    await db.commit()
    await db.refresh(channel)
    return (await _email_list_views(db, [channel]))[0]


@router.patch("/notifications/email-lists/{list_id}", response_model=EmailListOut)
async def update_email_list(
    list_id: uuid.UUID, body: EmailListUpdate, request: Request, db: DbSession, user: Manager
) -> EmailListOut:
    channel = await _email_list(db, user, list_id)
    current = EmailList.from_channel(channel)
    changes = body.model_fields_set
    project_id = body.project_id if "project_id" in changes else current.project_id
    environment_id = body.environment_id if "environment_id" in changes else current.environment_id
    if "project_id" in changes and "environment_id" not in changes and project_id != current.project_id:
        environment_id = None  # a new project scope cannot keep the old project's environment
    await _validate_email_scope(db, user, project_id, environment_id)
    channel.config = _email_config(
        body.recipients if body.recipients is not None else list(current.recipients),
        body.min_severity or current.min_severity,
        body.notify_resolved if body.notify_resolved is not None else current.notify_resolved,
        project_id,
        environment_id,
    )
    if body.name is not None:
        channel.name = body.name.strip()
    if body.enabled is not None:
        channel.enabled = body.enabled
    await record_audit(
        db,
        action="email_list.updated",
        user=user,
        target_type="email_list",
        target_id=str(channel.id),
        request=request,
        details=_audit_details(channel),
    )
    await db.commit()
    await db.refresh(channel)
    return (await _email_list_views(db, [channel]))[0]


@router.delete("/notifications/email-lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_email_list(list_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> None:
    channel = await _email_list(db, user, list_id)
    channel.deleted_at = datetime.now(UTC)
    await record_audit(
        db,
        action="email_list.deleted",
        user=user,
        target_type="email_list",
        target_id=str(channel.id),
        request=request,
        details={"name": channel.name},
    )
    await db.commit()


@router.post("/notifications/email-lists/{list_id}/test", response_model=dict[str, str])
async def test_email_list(list_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> dict[str, str]:
    channel = await _email_list(db, user, list_id)
    lst = EmailList.from_channel(channel)
    problem = await send_test_email(lst)
    outcome = (
        {"status": "sent", "message": f"Test email sent to {len(lst.recipients)} recipient(s)."}
        if problem is None
        else {"status": "failed", "message": problem}
    )
    await record_audit(
        db,
        action="email_list.tested",
        user=user,
        target_type="email_list",
        target_id=str(channel.id),
        request=request,
        result="success" if problem is None else "failure",
        details={"recipients": mask_all(lst.recipients)},
    )
    await db.commit()
    return outcome


# ---- Microsoft Teams alert channels ---------------------------------------------------------
#
# The Workflows webhook URL is a secret: only its Key Vault secret name is stored and returned.


@router.get("/notifications/teams-setup", response_model=TeamsSetupOut)
async def get_teams_setup(db: DbSession, user: Manager) -> dict[str, str]:
    settings = get_settings()
    if settings.key_vault_url:
        source = "key_vault"
    elif settings.environment in (AppEnvironment.development, AppEnvironment.test):
        source = "environment"
    else:
        source = "none"
    return {"secret_prefix": await _secret_prefix(db, user), "secret_source": source}


async def _teams_channel(db: DbSession, user: CurrentUser, channel_id: uuid.UUID) -> NotificationChannel:
    channel = await db.scalar(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.organization_id == user.organization_id,
            NotificationChannel.channel_type == TEAMS_CHANNEL,
            NotificationChannel.deleted_at.is_(None),
        )
    )
    if channel is None or not is_teams_subscription(channel):
        raise NotFoundError("Teams channel not found.")
    return channel


async def _teams_views(db: DbSession, channels: list[NotificationChannel]) -> list[TeamsChannelOut]:
    subs = [TeamsSubscription.from_channel(c) for c in channels]
    project_ids = {s.project_id for s in subs if s.project_id}
    env_ids = {s.environment_id for s in subs if s.environment_id}
    projects = (
        {p.id: p.name for p in await db.scalars(select(Project).where(Project.id.in_(project_ids)))}
        if project_ids
        else {}
    )
    envs = (
        {e.id: e.name for e in await db.scalars(select(Environment).where(Environment.id.in_(env_ids)))}
        if env_ids
        else {}
    )
    return [
        TeamsChannelOut(
            id=s.channel.id,
            name=s.channel.name,
            enabled=s.channel.enabled,
            secret_ref=s.channel.secret_ref,
            min_severity="warning" if s.min_severity == "warning" else "critical",
            notify_resolved=s.notify_resolved,
            project_id=s.project_id,
            environment_id=s.environment_id,
            project_name=projects.get(s.project_id) if s.project_id else None,
            environment_name=envs.get(s.environment_id) if s.environment_id else None,
            created_at=s.channel.created_at,
            updated_at=s.channel.updated_at,
        )
        for s in subs
    ]


def _teams_audit(channel: NotificationChannel) -> dict[str, object]:
    sub = TeamsSubscription.from_channel(channel)
    return {
        "name": channel.name,
        "secret_ref": channel.secret_ref,
        "min_severity": sub.min_severity,
        "notify_resolved": sub.notify_resolved,
        "enabled": channel.enabled,
        "project_id": str(sub.project_id) if sub.project_id else None,
        "environment_id": str(sub.environment_id) if sub.environment_id else None,
    }


@router.get("/notifications/teams-channels", response_model=list[TeamsChannelOut])
async def list_teams_channels(db: DbSession, user: Manager) -> list[TeamsChannelOut]:
    channels = [
        c
        for c in await db.scalars(
            select(NotificationChannel)
            .where(
                NotificationChannel.organization_id == user.organization_id,
                NotificationChannel.channel_type == TEAMS_CHANNEL,
                NotificationChannel.deleted_at.is_(None),
            )
            .order_by(NotificationChannel.name)
        )
        if is_teams_subscription(c)
    ]
    return await _teams_views(db, channels)


@router.post("/notifications/teams-channels", response_model=TeamsChannelOut, status_code=status.HTTP_201_CREATED)
async def create_teams_channel(body: TeamsChannelIn, request: Request, db: DbSession, user: Manager) -> TeamsChannelOut:
    await _check_secret_ref(db, user, body.secret_ref)
    await _validate_email_scope(db, user, body.project_id, body.environment_id)
    channel = NotificationChannel(
        organization_id=user.organization_id,
        name=body.name,
        channel_type=TEAMS_CHANNEL,
        enabled=body.enabled,
        secret_ref=body.secret_ref,
        config=teams_config(body.min_severity, body.notify_resolved, body.project_id, body.environment_id),
    )
    db.add(channel)
    await db.flush()
    await record_audit(
        db,
        action="teams_channel.created",
        user=user,
        target_type="notification_channel",
        target_id=str(channel.id),
        request=request,
        details=_teams_audit(channel),
    )
    await db.commit()
    await db.refresh(channel)
    return (await _teams_views(db, [channel]))[0]


@router.patch("/notifications/teams-channels/{channel_id}", response_model=TeamsChannelOut)
async def update_teams_channel(
    channel_id: uuid.UUID, body: TeamsChannelUpdate, request: Request, db: DbSession, user: Manager
) -> TeamsChannelOut:
    channel = await _teams_channel(db, user, channel_id)
    current = TeamsSubscription.from_channel(channel)
    changes = body.model_fields_set
    project_id = body.project_id if "project_id" in changes else current.project_id
    environment_id = body.environment_id if "environment_id" in changes else current.environment_id
    if "project_id" in changes and "environment_id" not in changes and project_id != current.project_id:
        environment_id = None  # a new project scope cannot keep the old project's environment
    await _validate_email_scope(db, user, project_id, environment_id)
    if body.secret_ref is not None:
        await _check_secret_ref(db, user, body.secret_ref)
        channel.secret_ref = body.secret_ref
    channel.config = teams_config(
        body.min_severity or current.min_severity,
        body.notify_resolved if body.notify_resolved is not None else current.notify_resolved,
        project_id,
        environment_id,
    )
    if body.name is not None:
        channel.name = body.name.strip()
    if body.enabled is not None:
        channel.enabled = body.enabled
    await record_audit(
        db,
        action="teams_channel.updated",
        user=user,
        target_type="notification_channel",
        target_id=str(channel.id),
        request=request,
        details=_teams_audit(channel),
    )
    await db.commit()
    await db.refresh(channel)
    return (await _teams_views(db, [channel]))[0]


@router.delete(
    "/notifications/teams-channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_teams_channel(channel_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> None:
    channel = await _teams_channel(db, user, channel_id)
    channel.deleted_at = datetime.now(UTC)
    await record_audit(
        db,
        action="teams_channel.deleted",
        user=user,
        target_type="notification_channel",
        target_id=str(channel.id),
        request=request,
        details={"name": channel.name},
    )
    await db.commit()


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
