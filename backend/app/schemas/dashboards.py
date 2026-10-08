from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

WidgetType = Literal[
    "metric_card",
    "gauge",
    "line_chart",
    "area_chart",
    "bar_chart",
    "resource_health",
    "alert_table",
    "log_table",
    "log_chart",
    "resource_table",
    "property_card",
    "app_insights_status",
    "dependency_map",
]


MAX_WIDGET_CONFIG_BYTES = 4096


class WidgetOut(ORMModel):
    id: uuid.UUID
    position: int
    section: str
    widget_type: str
    title: str
    width: int
    config: dict[str, Any]


class WidgetIn(BaseModel):
    section: str = Field(default="Overview", min_length=1, max_length=100)
    widget_type: WidgetType
    title: str = Field(min_length=1, max_length=200)
    width: int = Field(default=6, ge=1, le=12)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def _bounded_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Widget settings are a few metric keys and options; anything larger is not a real widget.
        if len(json.dumps(value, default=str)) > MAX_WIDGET_CONFIG_BYTES:
            raise ValueError(f"Widget settings are limited to {MAX_WIDGET_CONFIG_BYTES // 1024} KB.")
        return value


class DashboardSummary(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    kind: str
    resource_id: uuid.UUID | None
    template_version: int | None
    is_customized: bool
    updated_at: datetime
    resource_type: str | None = None
    type_display_name: str | None = None
    project_name: str | None = None
    environment_name: str | None = None
    health_status: str | None = None


class DashboardOut(DashboardSummary):
    widgets: list[WidgetOut]
    sections: list[str]


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    widgets: list[WidgetIn] | None = Field(default=None, max_length=100)


class TemplateOut(ORMModel):
    id: uuid.UUID
    key: str
    name: str
    description: str
    version: int
    monitor_key: str
    resource_types: list[str]
    definition: dict[str, Any]
