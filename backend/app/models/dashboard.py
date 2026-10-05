from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDelete, Timestamps, UUIDPrimaryKey


class DashboardTemplate(UUIDPrimaryKey, Timestamps, Base):
    """Versioned template registered by a monitor plugin (synced on start-up and on sync)."""

    __tablename__ = "dashboard_templates"

    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    monitor_key: Mapped[str] = mapped_column(String(60), index=True)
    resource_types: Mapped[list[Any]] = mapped_column(default=list)
    definition: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)


class Dashboard(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    __tablename__ = "dashboards"
    __table_args__ = (UniqueConstraint("organization_id", "resource_id", name="uq_dashboards_org_resource"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    #: resource (generated for one resource) | custom
    kind: Mapped[str] = mapped_column(String(20), default="resource")
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("resources.id"), nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("dashboard_templates.id"), nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: A customised dashboard is never overwritten by template upgrades.
    is_customized: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)

    widgets: Mapped[list[DashboardWidget]] = relationship(
        back_populates="dashboard", order_by="DashboardWidget.position", cascade="all, delete-orphan"
    )


class DashboardWidget(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "dashboard_widgets"

    dashboard_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("dashboards.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(String(100), default="Overview")
    widget_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    #: Column span on a 12-column grid.
    width: Mapped[int] = mapped_column(Integer, default=6)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)

    dashboard: Mapped[Dashboard] = relationship(back_populates="widgets")
