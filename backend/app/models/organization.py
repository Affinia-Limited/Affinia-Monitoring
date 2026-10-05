from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDelete, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.models.project import Project


class Organization(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    """Tenant boundary. Every other business row belongs to exactly one organization."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    #: Entra tenant whose users are provisioned into this organization on first sign-in.
    entra_tenant_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)

    users: Mapped[list[User]] = relationship(back_populates="organization")
    projects: Mapped[list[Project]] = relationship(back_populates="organization")


class Role(Timestamps, Base):
    """Application role definitions. Seeded by migration from ``app.core.permissions``."""

    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    permissions: Mapped[list[Any]] = mapped_column(default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)


class UserStatus(StrEnum):
    """Application membership state. Only ``active`` users can use the API."""

    #: Invited by an administrator; activated on the user's first matching Entra sign-in.
    pending = "pending"
    active = "active"
    #: Temporarily blocked; can be reactivated.
    suspended = "suspended"
    #: Access removed. The row is kept for the audit trail.
    deactivated = "deactivated"


class User(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    """A person allowed (or invited) to use the platform.

    Entra ID proves *who* someone is; this row decides *whether* they may use the
    platform. The permanent identity key is ``(organization_id, entra_tenant_id,
    entra_object_id)``; email is profile data only. Pending invitations have no
    object id yet: it is bound on the first matching sign-in and never changes after.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index(
            "uq_users_identity",
            "organization_id",
            "entra_tenant_id",
            "entra_object_id",
            unique=True,
            postgresql_where=text("entra_object_id IS NOT NULL"),
            sqlite_where=text("entra_object_id IS NOT NULL"),
        ),
        # At most one open invitation per email within an organisation and tenant.
        Index(
            "uq_users_pending_email",
            "organization_id",
            "entra_tenant_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_users_org_status", "organization_id", "status"),
        CheckConstraint("status IN ('pending', 'active', 'suspended', 'deactivated')", name="status"),
        CheckConstraint("entra_object_id IS NOT NULL OR status IN ('pending', 'deactivated')", name="identity_bound"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    #: Immutable Entra object id (``oid``). Null only while an invitation is pending.
    entra_object_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entra_tenant_id: Mapped[str] = mapped_column(String(64))
    #: Profile data (UPN / preferred_username), refreshed from the token. Lower-cased for invitations.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role_key: Mapped[str] = mapped_column(String(50), ForeignKey("roles.key"), default="viewer")
    #: When true the role is managed by Entra app-role assignments and cannot be edited in-app.
    role_managed_by_entra: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=UserStatus.pending.value)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invitation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The administrator who invited this user (null for bootstrap and development users).
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="users")
