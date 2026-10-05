"""Notification senders. Webhook-style endpoints are read from Key Vault at send time."""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx

from app.models import NotificationChannel
from app.services.alerts.channels.base import AlertNotification, ChannelNotConfiguredError, NotificationSender
from app.services.secrets import get_secret

_TIMEOUT = httpx.Timeout(10.0)


async def _endpoint(channel: NotificationChannel) -> str:
    if not channel.secret_ref:
        raise ChannelNotConfiguredError("No Key Vault secret reference configured.")
    url = await get_secret(channel.secret_ref)
    if urlparse(url).scheme != "https":
        raise ChannelNotConfiguredError("Notification endpoints must use HTTPS.")
    return url


async def _post(url: str, body: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        response = await client.post(url, json=body)
        response.raise_for_status()


class WebhookSender:
    channel_type: ClassVar[str] = "webhook"
    requires_secret: ClassVar[bool] = True

    async def send(self, channel: NotificationChannel, notification: AlertNotification) -> None:
        await _post(await _endpoint(channel), {"summary": notification.summary(), **notification.payload()})


class TeamsSender:
    """Microsoft Teams via a Workflows / incoming-webhook URL, as an Adaptive Card."""

    channel_type: ClassVar[str] = "teams"
    requires_secret: ClassVar[bool] = True

    async def send(self, channel: NotificationChannel, notification: AlertNotification) -> None:
        facts = [
            {"title": "Resource", "value": notification.resource_name},
            {"title": "Severity", "value": notification.severity},
            {"title": "Status", "value": notification.status},
        ]
        if notification.metric:
            facts.append({"title": "Metric", "value": notification.metric})
        if notification.current_value is not None:
            facts.append({"title": "Value", "value": f"{notification.current_value:g}"})
        if notification.threshold is not None:
            facts.append({"title": "Threshold", "value": f"{notification.threshold:g}"})
        card: dict[str, Any] = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": [
                {"type": "TextBlock", "text": notification.summary(), "weight": "Bolder", "wrap": True},
                {"type": "FactSet", "facts": facts},
            ],
        }
        if notification.link:
            card["actions"] = [{"type": "Action.OpenUrl", "title": "Open alert", "url": notification.link}]
        await _post(
            await _endpoint(channel),
            {
                "type": "message",
                "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}],
            },
        )


class SlackSender:
    channel_type: ClassVar[str] = "slack"
    requires_secret: ClassVar[bool] = True

    async def send(self, channel: NotificationChannel, notification: AlertNotification) -> None:
        text = notification.summary()
        if notification.link:
            text += f"\n<{notification.link}|Open alert>"
        await _post(await _endpoint(channel), {"text": text})


class EmailSender:
    """Placeholder until an email provider (e.g. Azure Communication Services) is chosen."""

    channel_type: ClassVar[str] = "email"
    requires_secret: ClassVar[bool] = False

    async def send(self, channel: NotificationChannel, notification: AlertNotification) -> None:
        raise ChannelNotConfiguredError("Email delivery is not configured in this deployment.")


SENDERS: dict[str, NotificationSender] = {
    s.channel_type: s for s in (WebhookSender(), TeamsSender(), SlackSender(), EmailSender())
}


def get_sender(channel_type: str) -> NotificationSender | None:
    return SENDERS.get(channel_type)
