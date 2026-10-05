from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ResourceOut(ORMModel):
    id: uuid.UUID
    azure_id: str
    name: str
    resource_type: str
    type_display_name: str = ""
    category: str = ""
    kind: str | None
    sku: str | None
    location: str | None
    subscription_id: str
    subscription_name: str | None = None
    resource_group: str
    tags: dict[str, str]
    monitor_key: str | None
    project_id: uuid.UUID | None
    project_name: str | None = None
    environment_id: uuid.UUID | None
    environment_name: str | None = None
    assignment_source: str
    health_status: str
    health_reasons: list[dict[str, Any]]
    health_evaluated_at: datetime | None
    #: Latest reading of each health-rule metric: {metric, label, unit, value, status, window_minutes}.
    health_metrics: list[dict[str, Any]] = []
    active_alerts: int = 0
    azure_availability_state: str | None
    last_seen_at: datetime | None
    first_seen_at: datetime | None
    dashboard_id: uuid.UUID | None = None


class ResourceDetail(ResourceOut):
    properties: dict[str, Any]
    related: dict[str, uuid.UUID | None] = {}
    summary_metrics: list[str] = []
    portal_url: str


class ResourceAssignment(BaseModel):
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None


class MetricCatalogEntry(BaseModel):
    key: str
    label: str
    unit: str
    aggregation: str
    split_by: str | None
    target: str
    description: str


class MetricSeriesOut(BaseModel):
    name: str
    dimensions: dict[str, str]
    points: list[dict[str, Any]]


class MetricOut(BaseModel):
    key: str
    label: str
    unit: str
    aggregation: str
    interval_seconds: int
    series: list[MetricSeriesOut]
    summary: dict[str, float | None]
    source_resource_id: str | None
    unavailable_reason: str | None
    unavailable_message: str | None
    is_mock: bool


class MetricsResponse(BaseModel):
    resource_id: uuid.UUID
    start: datetime
    end: datetime
    metrics: list[MetricOut]


class FacetValue(BaseModel):
    value: str
    label: str
    count: int


class ResourceFacets(BaseModel):
    resource_types: list[FacetValue]
    locations: list[FacetValue]
    resource_groups: list[FacetValue]
    subscriptions: list[FacetValue]
    health: list[FacetValue]
