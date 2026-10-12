"""Email lists: organisation-wide email subscriptions to alerts and health changes.

An email list is a ``NotificationChannel`` with ``channel_type="email"`` and config::

    {"recipients": [...], "min_severity": "critical" | "warning", "notify_resolved": bool,
     "project_id": "<uuid>" | None, "environment_id": "<uuid>" | None}

Lists receive every alert and health transition in their scope at or above their severity,
whatever channels an alert rule names. Sending never raises: failures are logged (addresses
masked) and recorded, so notification problems can never break an evaluation.
"""

from __future__ import annotations

import html
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_key, get_cache
from app.core.config import get_settings
from app.models import Alert, AlertEvent, Environment, NotificationChannel, Project, Resource
from app.services.email import EmailDeliveryError, EmailMessage, EmailNotConfiguredError, send_email
from app.services.monitors.registry import type_display_name

logger = logging.getLogger(__name__)

EMAIL_CHANNEL = "email"
#: The same resource flapping between states emails each list at most once per status in this window.
HEALTH_COOLDOWN_SECONDS = 30 * 60
_RANK = {"info": 0, "unknown": 0, "healthy": 0, "warning": 1, "critical": 2}


@dataclass(frozen=True)
class EmailList:
    id: uuid.UUID
    name: str
    recipients: tuple[str, ...]
    min_severity: str
    notify_resolved: bool
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None

    @classmethod
    def from_channel(cls, channel: NotificationChannel) -> EmailList:
        config: dict[str, Any] = channel.config or {}
        recipients = config.get("recipients") or []
        if isinstance(recipients, str):
            recipients = [r.strip() for r in recipients.split(",") if r.strip()]

        def _uuid(value: Any) -> uuid.UUID | None:
            try:
                return uuid.UUID(str(value)) if value else None
            except ValueError:
                return None

        return cls(
            id=channel.id,
            name=channel.name,
            recipients=tuple(str(r).lower() for r in recipients),
            min_severity="warning" if config.get("min_severity") == "warning" else "critical",
            notify_resolved=bool(config.get("notify_resolved", True)),
            project_id=_uuid(config.get("project_id")),
            environment_id=_uuid(config.get("environment_id")),
        )

    def covers(self, severity: str) -> bool:
        return _RANK.get(severity, 0) >= _RANK[self.min_severity]

    def in_scope(self, resource: Resource) -> bool:
        if self.project_id and resource.project_id != self.project_id:
            return False
        return not (self.environment_id and resource.environment_id != self.environment_id)


@dataclass(frozen=True)
class HealthTransition:
    resource_id: uuid.UUID
    previous: str
    current: str
    #: Short, human explanation of the new state (e.g. the worst health reason).
    reason: str


async def active_email_lists(db: AsyncSession, organization_id: uuid.UUID) -> list[EmailList]:
    channels = await db.scalars(
        select(NotificationChannel).where(
            NotificationChannel.organization_id == organization_id,
            NotificationChannel.channel_type == EMAIL_CHANNEL,
            NotificationChannel.enabled.is_(True),
            NotificationChannel.deleted_at.is_(None),
        )
    )
    return [lst for lst in (EmailList.from_channel(c) for c in channels) if lst.recipients]


def resource_link(resource_id: uuid.UUID | str) -> str | None:
    base = get_settings().public_base_url
    return f"{base.rstrip('/')}/resources/{resource_id}" if base else None


async def scope_names(db: AsyncSession, resource: Resource) -> tuple[str | None, str | None]:
    project = await db.get(Project, resource.project_id) if resource.project_id else None
    environment = await db.get(Environment, resource.environment_id) if resource.environment_id else None
    return (project.name if project else None, environment.name if environment else None)


def _render(
    *,
    heading: str,
    subject: str,
    facts: list[tuple[str, str]],
    link: str | None,
    footer: str,
    kind: str,
    recipients: tuple[str, ...],
) -> EmailMessage:
    text_lines = [heading, ""] + [f"{label}: {value}" for label, value in facts]
    if link:
        text_lines += ["", f"Open in the monitoring platform: {link}"]
    text_lines += ["", footer]
    rows = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#5b6474">{html.escape(label)}</td>'
        f'<td style="padding:4px 0">{html.escape(value)}</td></tr>'
        for label, value in facts
    )
    button = (
        f'<p><a href="{html.escape(link, quote=True)}" style="color:#1f5f99">Open in the monitoring platform</a></p>'
        if link
        else ""
    )
    body = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#111827">'
        f'<p style="font-size:16px;font-weight:bold">{html.escape(heading)}</p>'
        f"<table>{rows}</table>{button}"
        f'<p style="font-size:12px;color:#5b6474">{html.escape(footer)}</p></div>'
    )
    return EmailMessage(recipients=recipients, subject=subject, text="\n".join(text_lines), html=body, kind=kind)


def _footer(list_name: str) -> str:
    return f"You receive this because you are on the '{list_name}' email list of the Azure Monitoring Platform."


def _scope_text(project: str | None, environment: str | None) -> str:
    return " / ".join(p for p in (project, environment) if p)


async def _deliver(lst: EmailList, message: EmailMessage) -> str | None:
    """Send; return ``None`` on success or a short reason (never containing addresses)."""
    try:
        await send_email(message)
        return None
    except EmailNotConfiguredError:
        return "email delivery is not configured"
    except EmailDeliveryError:
        return "delivery failed"
    except Exception:  # never let a notification break an evaluation
        logger.exception("email_list_send_crashed", extra={"email_list_id": str(lst.id)})
        return "delivery failed"


async def send_alert_emails(db: AsyncSession, alert: Alert, event: str, resource: Resource) -> None:
    """Email every list whose scope and severity cover this alert. Records an AlertEvent per list."""
    lists = [
        lst
        for lst in await active_email_lists(db, alert.organization_id)
        if lst.covers(alert.severity) and lst.in_scope(resource) and (event == "fired" or lst.notify_resolved)
    ]
    if not lists:
        return
    project, environment = await scope_names(db, resource)
    scope = _scope_text(project, environment)
    prefix = "RESOLVED" if event == "resolved" else alert.severity.upper()
    subject = f"[{prefix}] {scope + ' - ' if scope else ''}{alert.title}"
    facts = [
        ("Resource", resource.name),
        ("Type", type_display_name(resource.resource_type, resource.monitor_key)),
        ("Project / environment", scope or "Unassigned"),
        ("Severity", alert.severity.capitalize()),
        ("Status", "Resolved" if event == "resolved" else "Firing"),
    ]
    if alert.metric_name:
        facts.append(("Metric", alert.metric_name))
    if alert.current_value is not None:
        facts.append(("Current value", f"{alert.current_value:g}"))
    if alert.threshold is not None:
        facts.append(("Threshold", f"{alert.threshold:g}"))
    facts.append(("Started", alert.started_at.strftime("%d/%m/%Y %H:%M UTC")))
    heading = ("Resolved: " if event == "resolved" else "Alert: ") + alert.title
    for lst in lists:
        message = _render(
            heading=heading,
            subject=subject[:250],
            facts=facts,
            link=resource_link(resource.id),
            footer=_footer(lst.name),
            kind="alert",
            recipients=lst.recipients,
        )
        problem = await _deliver(lst, message)
        if problem is None:
            db.add(AlertEvent(alert_id=alert.id, event_type="notified", message=f"Emailed list '{lst.name}'"))
        else:
            db.add(
                AlertEvent(
                    alert_id=alert.id, event_type="notification_failed", message=f"Email list '{lst.name}': {problem}"
                )
            )


def health_event(transition: HealthTransition) -> tuple[str, str] | None:
    """(severity that decides who is emailed, event) for a transition worth an email, else None."""
    previous, current = transition.previous, transition.current
    if current == "critical":
        return "critical", "critical"
    if current == "warning" and previous in ("healthy", "unknown"):
        return "warning", "warning"
    if current == "healthy" and previous in ("warning", "critical"):
        return previous, "recovered"
    return None


async def send_health_emails(db: AsyncSession, organization_id: uuid.UUID, transitions: list[HealthTransition]) -> int:
    """Email health transitions to the lists that cover them; returns the number of emails sent.

    Call only after the evaluation that produced ``transitions`` is committed. Never raises.
    """
    try:
        return await _send_health_emails(db, organization_id, transitions)
    except Exception:
        logger.exception("health_emails_failed", extra={"organization_id": str(organization_id)})
        return 0


async def _send_health_emails(db: AsyncSession, organization_id: uuid.UUID, transitions: list[HealthTransition]) -> int:
    worth = [(t, ev) for t in transitions if (ev := health_event(t))]
    if not worth:
        return 0
    lists = await active_email_lists(db, organization_id)
    if not lists:
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
    sent = 0
    for transition, (severity, event) in worth:
        resource = resources.get(transition.resource_id)
        if resource is None:
            continue
        targets = [
            lst
            for lst in lists
            if lst.covers(severity) and lst.in_scope(resource) and (event != "recovered" or lst.notify_resolved)
        ]
        if not targets:
            continue
        project, environment = await scope_names(db, resource)
        scope = _scope_text(project, environment)
        label = {"critical": "CRITICAL", "warning": "WARNING", "recovered": "RECOVERED"}[event]
        state = {"critical": "is critical", "warning": "needs attention", "recovered": "has recovered"}[event]
        detail = f": {transition.reason}" if transition.reason and event != "recovered" else ""
        summary = f"{resource.name} {state}{detail}"
        subject = f"[{label}] {scope + ' - ' if scope else ''}{summary}"
        facts = [
            ("Resource", resource.name),
            ("Type", type_display_name(resource.resource_type, resource.monitor_key)),
            ("Project / environment", scope or "Unassigned"),
            ("Health", f"{transition.previous.capitalize()} to {transition.current.capitalize()}"),
        ]
        if transition.reason and event != "recovered":
            facts.append(("Reason", transition.reason))
        for lst in targets:
            key = cache_key("email_cooldown", str(lst.id), str(resource.id), transition.current)
            if await cache.get(key):
                continue
            message = _render(
                heading=f"{resource.name} {state}",
                subject=subject[:250],
                facts=facts,
                link=resource_link(resource.id),
                footer=_footer(lst.name),
                kind="health",
                recipients=lst.recipients,
            )
            if await _deliver(lst, message) is None:
                await cache.set(key, 1, HEALTH_COOLDOWN_SECONDS)
                sent += 1
    return sent


async def send_test_email(lst: EmailList) -> str | None:
    """Send a test message to a list; ``None`` on success, otherwise a reason safe to show."""
    message = _render(
        heading="Test email from the Azure Monitoring Platform",
        subject="[TEST] Azure Monitoring Platform email notifications",
        facts=[("Email list", lst.name), ("Recipients", str(len(lst.recipients)))],
        link=get_settings().public_base_url,
        footer=_footer(lst.name),
        kind="test",
        recipients=lst.recipients,
    )
    try:
        await send_email(message)
        return None
    except EmailNotConfiguredError as exc:
        return str(exc)
    except EmailDeliveryError:
        return "The email could not be sent. Check the Azure Communication Services configuration."
