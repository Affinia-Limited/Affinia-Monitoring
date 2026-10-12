"""Alert templates and their assignments (see app.services.alerts.templates)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Tier = Literal["critical", "warning", "info", "ok", "unknown"]
Scope = Literal["resource", "environment", "project", "organization"]


class TemplateRuleOut(BaseModel):
    metric: str
    label: str
    unit: str
    description: str
    operator: Literal["gt", "gte", "lt", "lte"]
    reducer: Literal["avg", "sum", "max", "min"]
    window_minutes: int
    frequency_minutes: int
    info: float | None
    warning: float | None
    critical: float | None
    default_info: float | None
    default_warning: float | None
    default_critical: float | None
    default_window_minutes: int
    enabled: bool
    customized: bool


class AlertTemplateOut(BaseModel):
    monitor_key: str
    display_name: str
    category: str
    description: str
    #: Any rule customised by the organisation.
    customized: bool
    #: Monitored, non-deleted resources of this type.
    resource_count: int
    #: Of those, covered by an enabled assignment.
    covered_count: int
    rules: list[TemplateRuleOut]


class TemplateRuleIn(BaseModel):
    enabled: bool
    info: float | None = None
    warning: float | None = None
    critical: float | None = None
    #: ``None`` or omitted: the recommended window.
    window_minutes: int | None = Field(default=None, ge=5, le=1440)


class RuleOverride(BaseModel):
    """Per-resource-scope change to one template rule; omitted fields keep the organisation's value."""

    enabled: bool | None = None
    info: float | None = None
    warning: float | None = None
    critical: float | None = None


class AssignmentIn(BaseModel):
    resource_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None
    enabled: bool = True
    #: Keys ``<monitor_key>:<metric>``.
    overrides: dict[str, RuleOverride] = Field(default_factory=dict, max_length=200)
    notification_channel_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class AssignmentUpdate(BaseModel):
    enabled: bool | None = None
    #: Replaces the whole map when given.
    overrides: dict[str, RuleOverride] | None = Field(default=None, max_length=200)
    notification_channel_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)


class AssignmentOut(BaseModel):
    id: uuid.UUID
    scope: Scope
    resource_id: uuid.UUID | None
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    resource_name: str | None
    project_name: str | None
    environment_name: str | None
    enabled: bool
    overrides: dict[str, dict[str, bool | float | None]]
    notification_channel_ids: list[str]
    #: Resources whose most specific enabled assignment is this one.
    covered_resources: int
    #: Monitor keys among those resources.
    templates: list[str]
    created_at: datetime
    updated_at: datetime


class PlanRuleOut(TemplateRuleOut):
    current_value: float | None
    current_tier: Tier
    #: The covering assignment overrides this rule.
    overridden: bool


class AlertPlanOut(BaseModel):
    resource_id: uuid.UUID
    monitor_key: str | None
    template: AlertTemplateOut | None
    assignment: AssignmentOut | None
    rules: list[PlanRuleOut]
