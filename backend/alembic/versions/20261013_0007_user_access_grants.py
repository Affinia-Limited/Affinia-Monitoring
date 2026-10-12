"""user_access_grants: project / environment / resource scoped access for members

Revision ID: 9c3e1b7a5d24
Revises: 4f7a2d9c6e18
Create Date: 2026-10-13 09:00:00

Existing members (other than Super Admins, who are always unrestricted) receive one
"all projects" grant, so nobody loses access when scoped access is introduced.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "9c3e1b7a5d24"
down_revision: str | None = "4f7a2d9c6e18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    grants = op.create_table(
        "user_access_grants",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_user_access_grants_organization_id_organizations")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_access_grants_user_id_users")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_user_access_grants_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"], ["environments.id"], name=op.f("fk_user_access_grants_environment_id_environments")
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["resources.id"], name=op.f("fk_user_access_grants_resource_id_resources")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_user_access_grants_created_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_access_grants")),
    )
    op.create_index(
        op.f("ix_user_access_grants_organization_id"), "user_access_grants", ["organization_id"], unique=False
    )
    op.create_index("ix_user_access_grants_user", "user_access_grants", ["user_id"], unique=False)

    # Nobody loses access: every existing member except Super Admins gets "all projects".
    members = op.get_bind().execute(
        sa.text("SELECT id, organization_id FROM users WHERE deleted_at IS NULL AND role_key <> 'super_admin'")
    )
    now = datetime.now(UTC)
    rows = [
        {
            "id": uuid.uuid4(),
            "organization_id": organization_id,
            "user_id": user_id,
            "project_id": None,
            "environment_id": None,
            "resource_id": None,
            "created_by_id": None,
            "created_at": now,
            "updated_at": now,
        }
        for user_id, organization_id in members
    ]
    if rows:
        op.bulk_insert(grants, rows)


def downgrade() -> None:
    op.drop_index("ix_user_access_grants_user", table_name="user_access_grants")
    op.drop_index(op.f("ix_user_access_grants_organization_id"), table_name="user_access_grants")
    op.drop_table("user_access_grants")
