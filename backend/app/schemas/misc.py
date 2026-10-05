from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class MeOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    email: str | None
    display_name: str | None
    role: str
    permissions: list[str]
    role_managed_by_entra: bool
    auth_mode: str
    azure_provider: str


RoleKey = Literal["super_admin", "admin", "operator", "viewer"]
UserStatusKey = Literal["pending", "active", "suspended", "deactivated"]


class UserOut(ORMModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None
    first_name: str | None
    last_name: str | None
    role_key: str
    role_managed_by_entra: bool
    status: UserStatusKey
    last_login_at: datetime | None
    invited_at: datetime | None
    invitation_expires_at: datetime | None
    activated_at: datetime | None
    deactivated_at: datetime | None
    created_at: datetime
    created_by_name: str | None = None


class UserDetailOut(UserOut):
    """Includes the technical identity binding; only returned to user administrators."""

    entra_object_id: str | None
    entra_tenant_id: str


class UserInvite(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role_key: RoleKey = "viewer"
    display_name: str | None = Field(default=None, max_length=200)


class UserUpdate(BaseModel):
    role_key: RoleKey | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class RoleOut(BaseModel):
    key: str
    name: str
    description: str
    permissions: list[str]


class AuditOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    actor: str
    action: str
    target_type: str | None
    target_id: str | None
    result: str
    ip_address: str | None
    request_id: str | None
    details: dict[str, Any]
    created_at: datetime


class LogTarget(BaseModel):
    resource_id: uuid.UUID
    name: str
    resource_type: str
    type_display_name: str
    project_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None
    project_name: str | None
    environment_name: str | None
    query_count: int


class PredefinedQuery(BaseModel):
    key: str
    title: str
    description: str
    category: str
    kql: str
    visualization: str
    target: str
    supports_severity: bool


class LogQueryIn(BaseModel):
    resource_id: uuid.UUID
    query_key: str | None = Field(default=None, max_length=80)
    kql: str | None = Field(default=None, max_length=10_000)
    time_range: str = "1h"
    start: datetime | None = None
    end: datetime | None = None
    search: str | None = Field(default=None, max_length=200)
    severities: list[str] = Field(default_factory=list, max_length=10)


class LogQueryOut(BaseModel):
    resource_id: uuid.UUID
    executed_against: uuid.UUID
    query: str
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    partial_error: str | None
    visualization: str
    is_mock: bool
    start: datetime
    end: datetime


class SearchHit(BaseModel):
    kind: Literal["project", "environment", "resource", "alert", "logs", "subscription"]
    id: str
    title: str
    subtitle: str
    url: str
    health_status: str | None = None
    #: Context so results are unambiguous: where the hit lives.
    project_name: str | None = None
    environment_name: str | None = None
    type_display_name: str | None = None
    severity: str | None = None


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHit]


class ComparisonRow(BaseModel):
    monitor_key: str
    monitor_name: str
    metric: str
    label: str
    unit: str
    rollup: str
    values: dict[str, float | None]
    resource_counts: dict[str, int]


class ComparisonOut(BaseModel):
    project_id: uuid.UUID
    environments: list[dict[str, Any]]
    rows: list[ComparisonRow]
    start: datetime
    end: datetime
    is_mock: bool
