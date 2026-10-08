from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDelete, Timestamps, UUIDPrimaryKey


class AzureConnection(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    """A tenant the platform identity has been granted read access to.

    Only metadata is stored. There are no credentials in this table: the platform
    authenticates with its own Managed Identity / Workload Identity, which the
    customer grants read-only Azure RBAC roles on the subscriptions below.
    """

    __tablename__ = "azure_connections"

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    tenant_id: Mapped[str] = mapped_column(String(64))
    #: managed_identity | workload_identity | developer (az login, development only)
    auth_method: Mapped[str] = mapped_column(String(40), default="managed_identity")
    #: pending | connected | error | disabled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True)
    default_environment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("environments.id"), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="connection",
        primaryjoin="and_(Subscription.connection_id == AzureConnection.id, Subscription.deleted_at.is_(None))",
        viewonly=True,
    )


class Subscription(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("organization_id", "subscription_id", name="uq_subscriptions_org_sub"),
        # A subscription is actively connected to at most one organisation.
        Index(
            "uq_subscriptions_active_subscription",
            "subscription_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("azure_connections.id"), index=True)
    subscription_id: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    tenant_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(40), default="Unknown")
    resource_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connection: Mapped[AzureConnection] = relationship(back_populates="subscriptions")


class ResourceGroup(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    __tablename__ = "resource_groups"
    __table_args__ = (UniqueConstraint("organization_id", "azure_id", name="uq_resource_groups_org_azure_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    subscription_ref_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"), index=True)
    #: Lower-cased ARM id, e.g. /subscriptions/<id>/resourcegroups/rg-crm-prod
    azure_id: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tags: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Resource(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    """A discovered Azure resource. ``deleted_at`` marks resources no longer present in Azure."""

    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("organization_id", "azure_id", name="uq_resources_org_azure_id"),
        Index("ix_resources_org_type", "organization_id", "resource_type"),
        Index("ix_resources_project_env", "project_id", "environment_id"),
        Index("ix_resources_environment", "environment_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("azure_connections.id"), index=True)
    subscription_ref_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"), index=True)
    resource_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("resource_groups.id"), nullable=True, index=True
    )
    #: Lower-cased ARM resource id. The stable identity used for de-duplication.
    azure_id: Mapped[str] = mapped_column(String(800))
    name: Mapped[str] = mapped_column(String(260), index=True)
    #: Lower-cased ARM type, e.g. microsoft.web/sites
    resource_type: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    subscription_id: Mapped[str] = mapped_column(String(64), index=True)
    resource_group: Mapped[str] = mapped_column(String(200), index=True)
    tags: Mapped[dict[str, Any]] = mapped_column(default=dict)
    #: Allow-listed, non-sensitive properties captured at discovery (see monitors).
    properties: Mapped[dict[str, Any]] = mapped_column(default=dict)
    #: Key of the monitor plugin handling this resource, or None if unsupported.
    monitor_key: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)

    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True)
    environment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("environments.id"), nullable=True)
    #: tag | name | connection_default | manual | none. Manual assignments survive sync.
    assignment_source: Mapped[str] = mapped_column(String(30), default="none")

    #: healthy | warning | critical | unknown
    health_status: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    health_reasons: Mapped[list[Any]] = mapped_column(default=list)
    #: Latest value of every health-rule metric read during evaluation (healthy ones included), in the
    #: monitor's rule order, so dashboards can show key metrics without extra Azure calls.
    health_metrics: Mapped[list[Any]] = mapped_column(default=list)
    health_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Azure Resource Health availabilityState (Available/Degraded/Unavailable/Unknown).
    azure_availability_state: Mapped[str | None] = mapped_column(String(30), nullable=True)

    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncRun(UUIDPrimaryKey, Timestamps, Base):
    """One execution of discovery/synchronisation for a connection, with step-by-step progress."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        # One queued or running sync per connection, even when requests race.
        Index(
            "uq_sync_runs_active_connection",
            "connection_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("azure_connections.id"), index=True)
    #: initial | manual | scheduled
    trigger: Mapped[str] = mapped_column(String(20))
    #: queued | running | succeeded | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    steps: Mapped[list[Any]] = mapped_column(default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Updated whenever the running job saves progress; a running sync without one is abandoned.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
