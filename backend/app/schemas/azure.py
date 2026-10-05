from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import GUID_PATTERN, ORMModel


def _clean_subscription_ids(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for v in values:
        v = v.strip().lower()
        if not re.fullmatch(GUID_PATTERN, v):
            raise ValueError("Each subscription id must be a GUID.")
        if v not in cleaned:
            cleaned.append(v)
    return cleaned


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tenant_id: str = Field(pattern=GUID_PATTERN)
    subscription_ids: list[str] = Field(min_length=1, max_length=200)
    auth_method: Literal["managed_identity", "workload_identity", "developer"] = "managed_identity"
    default_project_id: uuid.UUID | None = None
    default_environment_id: uuid.UUID | None = None

    @field_validator("subscription_ids")
    @classmethod
    def _validate_subs(cls, values: list[str]) -> list[str]:
        return _clean_subscription_ids(values)

    @field_validator("tenant_id")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sync_enabled: bool | None = None
    default_project_id: uuid.UUID | None = None
    default_environment_id: uuid.UUID | None = None
    add_subscription_ids: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("add_subscription_ids")
    @classmethod
    def _validate_subs(cls, values: list[str]) -> list[str]:
        return _clean_subscription_ids(values)


class SubscriptionOut(ORMModel):
    id: uuid.UUID
    subscription_id: str
    display_name: str
    tenant_id: str
    state: str
    resource_count: int
    last_synced_at: datetime | None


class SyncStep(BaseModel):
    key: str
    label: str
    status: str
    detail: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class SyncRunOut(ORMModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    trigger: str
    status: str
    steps: list[SyncStep]
    stats: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime


class ConnectionOut(ORMModel):
    id: uuid.UUID
    name: str
    tenant_id: str
    auth_method: str
    status: str
    sync_enabled: bool
    last_sync_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    default_project_id: uuid.UUID | None
    default_environment_id: uuid.UUID | None
    created_at: datetime
    subscriptions: list[SubscriptionOut] = []
    resource_count: int = 0
    latest_run: SyncRunOut | None = None


class ConnectionCreated(BaseModel):
    connection: ConnectionOut
    sync_run: SyncRunOut


class PlatformIdentityOut(BaseModel):
    """What an administrator needs to grant access; contains no secrets."""

    provider: str
    auth_methods: list[str]
    client_id: str | None
    home_tenant_id: str | None
    required_roles: list[dict[str, str]]
    is_mock: bool
