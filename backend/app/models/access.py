"""Scoped access: which projects, environments and resources a member may use.

A member's role decides *what* they may do; their grants decide *where*. Grants are hierarchical:

* ``project_id`` null: every project (and unassigned resources) - "all projects"
* ``project_id`` set, ``environment_id`` null: the whole project
* ``environment_id`` set, ``resource_id`` null: the whole environment
* ``resource_id`` set: that resource only (while it stays in that environment)

Super Admins are unrestricted and need no grants. A member without grants sees nothing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


class UserAccessGrant(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "user_access_grants"
    __table_args__ = (Index("ix_user_access_grants_user", "user_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True)
    environment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("environments.id"), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("resources.id"), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
