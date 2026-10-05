from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

Severity = Literal["critical", "warning", "info"]
OperatorT = Literal["gt", "gte", "lt", "lte"]


class AlertOut(ORMModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None
    resource_id: uuid.UUID
    resource_name: str | None = None
    resource_type: str | None = None
    type_display_name: str | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    environment_id: uuid.UUID | None = None
    environment_name: str | None = None
    source: str
    severity: str
    status: str
    title: str
    metric_name: str | None
    unit: str | None = None
    current_value: float | None
    threshold: float | None
    operator: str | None
    started_at: datetime
    last_evaluated_at: datetime | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None


class AlertEventOut(ORMModel):
    id: uuid.UUID
    event_type: str
    message: str
    value: float | None
    actor_user_id: uuid.UUID | None
    created_at: datetime


class AlertDetail(AlertOut):
    events: list[AlertEventOut]


class AlertRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    monitor_key: str = Field(min_length=1, max_length=60)
    metric_name: str = Field(min_length=1, max_length=120)
    aggregation: Literal["Average", "Total", "Maximum", "Minimum", "Count"] = "Average"
    operator: OperatorT = "gt"
    threshold: float
    severity: Severity = "warning"
    window_minutes: int = Field(default=15, ge=5, le=1440)
    resource_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None
    notification_channel_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class AlertRuleOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    enabled: bool
    monitor_key: str
    metric_name: str
    aggregation: str
    operator: str
    threshold: float
    severity: str
    window_minutes: int
    resource_id: uuid.UUID | None
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    notification_channel_ids: list[uuid.UUID]
    created_at: datetime


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    channel_type: Literal["webhook", "teams", "slack", "email"]
    enabled: bool = True
    #: Name of the Key Vault secret holding the endpoint URL. Never the URL itself.
    secret_ref: str | None = Field(default=None, pattern=r"^[0-9a-zA-Z-]{1,127}$")
    config: dict[str, str | list[str]] = Field(default_factory=dict)


class ChannelOut(ORMModel):
    id: uuid.UUID
    name: str
    channel_type: str
    enabled: bool
    secret_ref: str | None
    config: dict[str, str | list[str]]
    created_at: datetime


class HealthThresholdIn(BaseModel):
    monitor_key: str = Field(min_length=1, max_length=60)
    metric_name: str = Field(min_length=1, max_length=120)
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    enabled: bool = True


class HealthRuleOut(BaseModel):
    monitor_key: str
    monitor_name: str
    metric_name: str
    metric_label: str
    unit: str
    operator: str
    window_minutes: int
    default_warning: float | None
    default_critical: float | None
    warning_threshold: float | None
    critical_threshold: float | None
    enabled: bool
    overridden: bool
