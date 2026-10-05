from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDelete, Timestamps, UUIDPrimaryKey


class HealthThreshold(UUIDPrimaryKey, Timestamps, Base):
    """Organisation override of a monitor's default health rule."""

    __tablename__ = "health_thresholds"
    __table_args__ = (
        UniqueConstraint("organization_id", "monitor_key", "metric_name", name="uq_health_thresholds_rule"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    monitor_key: Mapped[str] = mapped_column(String(60))
    metric_name: Mapped[str] = mapped_column(String(120))
    warning_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationChannel(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    """Delivery target for alert notifications.

    Secret endpoints (webhook URLs, Teams/Slack incoming webhooks) are NOT stored
    here: ``secret_ref`` is the name of a Key Vault secret resolved at send time.
    """

    __tablename__ = "notification_channels"

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    #: webhook | teams | slack | email
    channel_type: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    secret_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Non-secret settings, e.g. email recipients.
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)


class AlertRule(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    __tablename__ = "alert_rules"

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Applies to resources handled by this monitor, optionally narrowed by the scope columns.
    monitor_key: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("resources.id"), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True)
    environment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("environments.id"), nullable=True)
    metric_name: Mapped[str] = mapped_column(String(120))
    aggregation: Mapped[str] = mapped_column(String(20), default="Average")
    #: gt | gte | lt | lte
    operator: Mapped[str] = mapped_column(String(5), default="gt")
    threshold: Mapped[float] = mapped_column(Float)
    #: critical | warning | info
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    window_minutes: Mapped[int] = mapped_column(Integer, default=15)
    notification_channel_ids: Mapped[list[Any]] = mapped_column(default=list)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)


class Alert(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_org_status", "organization_id", "status"),
        Index("ix_alerts_fingerprint", "organization_id", "fingerprint"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("alert_rules.id"), nullable=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("resources.id"), index=True)
    #: Stable identity of the condition (rule + resource) used to de-duplicate firing.
    fingerprint: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(30), default="platform")
    severity: Mapped[str] = mapped_column(String(20))
    #: active | acknowledged | resolved
    status: Mapped[str] = mapped_column(String(20), default="active")
    title: Mapped[str] = mapped_column(String(300))
    metric_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(5), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlertEvent(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "alert_events"

    alert_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("alerts.id"), index=True)
    #: fired | value_updated | acknowledged | resolved | reopened | notified | notification_failed
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
