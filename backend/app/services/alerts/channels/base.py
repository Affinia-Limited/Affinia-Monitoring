"""Notification channel interface.

New integrations (PagerDuty, ServiceNow, ...) implement ``NotificationSender``
and register in ``app.services.alerts.channels.registry``. No other code changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from app.models import NotificationChannel


@dataclass(frozen=True)
class AlertNotification:
    event: str  # fired | resolved | test
    alert_id: str
    title: str
    severity: str
    status: str
    project: str | None
    environment: str | None
    resource_name: str
    resource_type: str
    metric: str | None
    current_value: float | None
    threshold: float | None
    started_at: str
    link: str | None

    def summary(self) -> str:
        scope = " / ".join(p for p in (self.project, self.environment) if p)
        prefix = "RESOLVED" if self.event == "resolved" else self.severity.upper()
        return f"[{prefix}] {scope + ' - ' if scope else ''}{self.title}"

    def payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


class ChannelNotConfiguredError(Exception):
    pass


class NotificationSender(Protocol):
    channel_type: ClassVar[str]
    requires_secret: ClassVar[bool]

    async def send(self, channel: NotificationChannel, notification: AlertNotification) -> None: ...
