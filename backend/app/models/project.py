from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDelete, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.models.organization import Organization


class Project(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_projects_org_slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    #: Azure tag values that map a resource to this project (case-insensitive), e.g. ["crm"].
    tag_values: Mapped[list[Any]] = mapped_column(default=list)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    environments: Mapped[list[Environment]] = relationship(
        back_populates="project",
        order_by="Environment.sort_order",
        primaryjoin="and_(Environment.project_id == Project.id, Environment.deleted_at.is_(None))",
        viewonly=True,
    )


class Environment(UUIDPrimaryKey, Timestamps, SoftDelete, Base):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_environments_project_slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(100))
    #: development | uat | staging | production | other
    kind: Mapped[str] = mapped_column(String(30), default="other")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    #: Azure tag values that map a resource to this environment, e.g. ["prod", "production"].
    tag_values: Mapped[list[Any]] = mapped_column(default=list)

    project: Mapped[Project] = relationship(back_populates="environments")
