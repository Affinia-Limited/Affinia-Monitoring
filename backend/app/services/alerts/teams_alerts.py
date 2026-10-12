"""Microsoft Teams alert channels: organisation-wide Teams subscriptions to alerts and health changes.

A Teams alert channel is a ``NotificationChannel`` with ``channel_type="teams"`` whose ``secret_ref``
names the Key Vault secret holding the channel's Workflows webhook URL, and whose config is::

    {"subscription": "on", "min_severity": "critical" | "warning", "notify_resolved": "true" | "false",
     "project_id": "<uuid>", "environment_id": "<uuid>"}       # scope keys are optional

Values are strings so the channel stays readable through the generic channel API. Like email lists,
these channels receive every alert and health transition in their scope at or above their severity,
whatever channels an alert rule names. Teams channels without ``subscription`` keep the original
behaviour: they post only for the alert rules that name them.

Posting never raises: failures are logged and recorded, so they can never break an evaluation.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_key, get_cache
from app.models import Alert, AlertEvent, NotificationChannel, Resource
from app.services.alerts.channels.base import AlertNotification, ChannelNotConfiguredError
from app.services.alerts.channels.registry import get_sender
from app.services.alerts.email_lists import (
    HEALTH_COOLDOWN_SECONDS,
    HealthTransition,
    health_event,
    resource_link,
    scope_names,
    send_health_emails,
)
from app.services.monitors.registry import type_display_name

logger = logging.getLogger(__name__)

TEAMS_CHANNEL = "teams"
_RANK = {"info": 0, "unknown": 0, "healthy": 0, "warning": 1, "critical": 2}


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def is_teams_subscription(channel: NotificationChannel) -> bool:
    return channel.channel_type == TEAMS_CHANNEL and (channel.config or {}).get("subscription") == "on"


@dataclass(frozen=True)
class TeamsSubscription:
    channel: NotificationChannel
    min_severity: str
    notify_resolved: bool
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None

    @classmethod
    def from_channel(cls, channel: NotificationChannel) -> TeamsSubscription:
        config: dict[str, Any] = channel.config or {}
        return cls(
            channel=channel,
            min_severity="warning" if config.get("min_severity") == "warning" else "critical",
            notify_resolved=str(config.get("notify_resolved", "true")).lower() != "false",
            project_id=_uuid(config.get("project_id")),
            environment_id=_uuid(config.get("environment_id")),
        )

    def covers(self, severity: str) -> bool:
        return _RANK.get(severity, 0) >= _RANK[self.min_severity]

    def in_scope(self, resource: Resource) -> bool:
        if self.project_id and resource.project_id != self.project_id:
            return False
        return not (self.environment_id and resource.environment_id != self.environment_id)


def teams_config(
    min_severity: str,
    notify_resolved: bool,
    project_id: uuid.UUID | None,
    environment_id: uuid.UUID | None,
) -> dict[str, str]:
    config = {
        "subscription": "on",
        "min_severity": min_severity,
        "notify_resolved": "true" if notify_resolved else "false",
    }
    if project_id:
        config["project_id"] = str(project_id)
    if environment_id:
        config["environment_id"] = str(environment_id)
    return config


async def active_teams_subscriptions(db: AsyncSession, organization_id: uuid.UUID) -> list[TeamsSubscription]:
    channels = await db.scalars(
        select(NotificationChannel).where(
            NotificationChannel.organization_id == organization_id,
            NotificationChannel.channel_type == TEAMS_CHANNEL,
            NotificationChannel.enabled.is_(True),
            NotificationChannel.deleted_at.is_(None),
        )
    )
    return [TeamsSubscription.from_channel(c) for c in channels if is_teams_subscription(c)]


async def _post(channel: NotificationChannel, notification: AlertNotification) -> str | None:
    """Post a card; return ``None`` on success or a short reason that is safe to show."""
    sender = get_sender(TEAMS_CHANNEL)
    try:
        if sender is None:
            raise ChannelNotConfiguredError("Teams delivery is not available.")
        await sender.send(channel, notification)
        return None
    except ChannelNotConfiguredError as exc:
        return str(exc)
    except Exception as exc:  # never let a notification break an evaluation
        logger.warning("teams_post_failed", extra={"channel_id": str(channel.id), "error_type": type(exc).__name__})
        return "delivery failed"


async def send_alert_teams(db: AsyncSession, alert: Alert, event: str, resource: Resource) -> set[uuid.UUID]:
    """Post an alert to every subscribed Teams channel covering it.

    Returns the ids of the subscribed channels whose scope and severity cover the alert: their own
    settings decide delivery, so the rule-level dispatch must skip them (no duplicate posts).
    """
    covering = [
        s
        for s in await active_teams_subscriptions(db, alert.organization_id)
        if s.covers(alert.severity) and s.in_scope(resource)
    ]
    targets = [s for s in covering if event == "fired" or s.notify_resolved]
    if targets:
        project, environment = await scope_names(db, resource)
        notification = AlertNotification(
            event=event,
            alert_id=str(alert.id),
            title=alert.title,
            severity=alert.severity,
            status="resolved" if event == "resolved" else alert.status,
            project=project,
            environment=environment,
            resource_name=resource.name,
            resource_type=type_display_name(resource.resource_type, resource.monitor_key),
            metric=alert.metric_name,
            current_value=alert.current_value,
            threshold=alert.threshold,
            started_at=alert.started_at.isoformat(),
            link=resource_link(resource.id),
        )
        for sub in targets:
            problem = await _post(sub.channel, notification)
            if problem is None:
                db.add(
                    AlertEvent(
                        alert_id=alert.id, event_type="notified", message=f"Posted to Teams '{sub.channel.name}'"
                    )
                )
            else:
                db.add(
                    AlertEvent(
                        alert_id=alert.id,
                        event_type="notification_failed",
                        message=f"Teams '{sub.channel.name}': {problem}",
                    )
                )
    return {s.channel.id for s in covering}


async def send_health_teams(db: AsyncSession, organization_id: uuid.UUID, transitions: list[HealthTransition]) -> int:
    """Post health transitions to the subscribed Teams channels that cover them. Never raises."""
    try:
        return await _send_health_teams(db, organization_id, transitions)
    except Exception:
        logger.exception("health_teams_failed", extra={"organization_id": str(organization_id)})
        return 0


async def _send_health_teams(db: AsyncSession, organization_id: uuid.UUID, transitions: list[HealthTransition]) -> int:
    worth = [(t, ev) for t in transitions if (ev := health_event(t))]
    if not worth:
        return 0
    subscriptions = await active_teams_subscriptions(db, organization_id)
    if not subscriptions:
        return 0
    resources = {
        r.id: r
        for r in await db.scalars(
            select(Resource).where(
                Resource.organization_id == organization_id,
                Resource.id.in_([t.resource_id for t, _ in worth]),
                Resource.deleted_at.is_(None),
            )
        )
    }
    cache = get_cache()
    posted = 0
    for transition, (severity, event) in worth:
        resource = resources.get(transition.resource_id)
        if resource is None:
            continue
        targets = [
            s
            for s in subscriptions
            if s.covers(severity) and s.in_scope(resource) and (event != "recovered" or s.notify_resolved)
        ]
        if not targets:
            continue
        project, environment = await scope_names(db, resource)
        state = {"critical": "is critical", "warning": "needs attention", "recovered": "has recovered"}[event]
        detail = f": {transition.reason}" if transition.reason and event != "recovered" else ""
        notification = AlertNotification(
            event="resolved" if event == "recovered" else "fired",
            alert_id="",
            title=f"{resource.name} {state}{detail}",
            severity=severity,
            status=f"{transition.previous.capitalize()} to {transition.current.capitalize()}",
            project=project,
            environment=environment,
            resource_name=resource.name,
            resource_type=type_display_name(resource.resource_type, resource.monitor_key),
            metric=None,
            current_value=None,
            threshold=None,
            started_at=datetime.now(UTC).isoformat(),
            link=resource_link(resource.id),
        )
        for sub in targets:
            key = cache_key("teams_cooldown", str(sub.channel.id), str(resource.id), transition.current)
            if await cache.get(key):
                continue
            if await _post(sub.channel, notification) is None:
                await cache.set(key, 1, HEALTH_COOLDOWN_SECONDS)
                posted += 1
    return posted


async def notify_health_transitions(
    db: AsyncSession, organization_id: uuid.UUID, transitions: list[HealthTransition]
) -> None:
    """Every subscription channel (email lists and Teams) for a committed health evaluation. Never raises."""
    await send_health_emails(db, organization_id, transitions)
    await send_health_teams(db, organization_id, transitions)
