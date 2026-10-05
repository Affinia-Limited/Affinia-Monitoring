from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import SLUG_PATTERN, ORMModel

EnvironmentKind = Literal["development", "uat", "staging", "production", "other"]


def _clean_tags(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for v in values:
        v = v.strip()
        if v and len(v) <= 100 and v.lower() not in (c.lower() for c in cleaned):
            cleaned.append(v)
    return cleaned[:20]


class EnvironmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(pattern=SLUG_PATTERN)
    kind: EnvironmentKind = "other"
    sort_order: int = Field(default=0, ge=0, le=1000)
    tag_values: list[str] = Field(default_factory=list)

    @field_validator("tag_values")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: EnvironmentKind | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    tag_values: list[str] | None = None


class EnvironmentOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    slug: str
    kind: str
    sort_order: int
    tag_values: list[str]


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN)
    description: str = Field(default="", max_length=2000)
    tag_values: list[str] = Field(default_factory=list)
    #: Convenience: create these environments with the project.
    environments: list[EnvironmentIn] = Field(default_factory=list, max_length=20)

    @field_validator("tag_values")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tag_values: list[str] | None = None


class HealthCounts(BaseModel):
    healthy: int = 0
    warning: int = 0
    critical: int = 0
    unknown: int = 0
    total: int = 0


class EnvironmentSummary(EnvironmentOut):
    health: HealthCounts = HealthCounts()
    status: str = "unknown"
    active_alerts: int = 0
    #: Most recent health evaluation of any monitored resource in the environment.
    last_checked_at: datetime | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    tag_values: list[str]
    created_at: datetime
    environments: list[EnvironmentSummary] = []
    health: HealthCounts = HealthCounts()
    status: str = "unknown"
    active_alerts: int = 0
    last_checked_at: datetime | None = None
