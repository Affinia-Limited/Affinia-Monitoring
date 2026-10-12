from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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


# ---- email lists -------------------------------------------------------------------------

#: Practical address check (RFC 5321 lengths, dot-atom local part, a dotted domain of valid labels).
_EMAIL = re.compile(
    r"^(?=.{3,254}$)(?=[^@]{1,64}@)[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
MAX_RECIPIENTS = 50


def clean_recipients(values: list[str]) -> list[str]:
    """Trimmed, lower-cased, de-duplicated (order kept). Invalid addresses are refused, not dropped."""
    cleaned: list[str] = []
    invalid = 0
    for value in values:
        address = value.strip().lower()
        if not address:
            continue
        if not _EMAIL.match(address):
            invalid += 1
        elif address not in cleaned:
            cleaned.append(address)
    if invalid:
        # The addresses themselves are not echoed back (personal data).
        raise ValueError(f"{invalid} recipient address(es) are not valid email addresses")
    if not cleaned:
        raise ValueError("Add at least one recipient")
    if len(cleaned) > MAX_RECIPIENTS:
        raise ValueError(f"An email list can have at most {MAX_RECIPIENTS} recipients")
    return cleaned


class EmailListIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    recipients: list[str] = Field(min_length=1, max_length=200)
    #: ``critical``: critical only. ``warning``: critical and warning.
    min_severity: Literal["critical", "warning"] = "critical"
    #: Also email when an alert resolves or a resource recovers.
    notify_resolved: bool = True
    enabled: bool = True
    project_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, v: list[str]) -> list[str]:
        return clean_recipients(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Enter a name")
        return v.strip()


class EmailListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    recipients: list[str] | None = Field(default=None, min_length=1, max_length=200)
    min_severity: Literal["critical", "warning"] | None = None
    notify_resolved: bool | None = None
    enabled: bool | None = None
    #: ``null`` clears the scope (all projects / all environments).
    project_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else clean_recipients(v)

    @model_validator(mode="after")
    def _no_nulls(self) -> EmailListUpdate:
        nulls = [
            f
            for f in ("name", "recipients", "min_severity", "notify_resolved", "enabled")
            if f in self.model_fields_set and getattr(self, f) is None
        ]
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null; omit the field to leave it unchanged")
        return self


class EmailListOut(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    recipients: list[str]
    min_severity: Literal["critical", "warning"]
    notify_resolved: bool
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    project_name: str | None = None
    environment_name: str | None = None
    created_at: datetime
    updated_at: datetime


class EmailStatusOut(BaseModel):
    #: acs | log | none
    provider: str
    configured: bool


class TestResultOut(BaseModel):
    status: Literal["sent", "failed"]
    message: str


class TeamsChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    #: Name of the Key Vault secret holding the Teams Workflows webhook URL. Never the URL itself.
    secret_ref: str = Field(pattern=r"^[0-9a-zA-Z-]{1,127}$")
    #: ``critical``: critical only. ``warning``: critical and warning.
    min_severity: Literal["critical", "warning"] = "critical"
    #: Also post when an alert resolves or a resource recovers.
    notify_resolved: bool = True
    enabled: bool = True
    project_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Enter a name")
        return v.strip()


class TeamsChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    secret_ref: str | None = Field(default=None, pattern=r"^[0-9a-zA-Z-]{1,127}$")
    min_severity: Literal["critical", "warning"] | None = None
    notify_resolved: bool | None = None
    enabled: bool | None = None
    #: ``null`` clears the scope (all projects / all environments).
    project_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> TeamsChannelUpdate:
        nulls = [
            f
            for f in ("name", "secret_ref", "min_severity", "notify_resolved", "enabled")
            if f in self.model_fields_set and getattr(self, f) is None
        ]
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null; omit the field to leave it unchanged")
        return self


class TeamsChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    secret_ref: str | None
    min_severity: Literal["critical", "warning"]
    notify_resolved: bool
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    project_name: str | None = None
    environment_name: str | None = None
    created_at: datetime
    updated_at: datetime


class TeamsSetupOut(BaseModel):
    #: Every Teams secret name must start with this (Key Vault is shared by all organisations).
    secret_prefix: str
    #: ``key_vault`` in Azure; ``environment`` (SECRET_<NAME> variables) in local development.
    secret_source: Literal["key_vault", "environment", "none"]
