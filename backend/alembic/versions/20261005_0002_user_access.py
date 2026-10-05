"""admin-controlled user access: membership status, invitations, identity binding

* ``users.status`` (pending | active | suspended | deactivated) replaces ``is_active``.
* ``entra_object_id`` becomes nullable: pending invitations are bound on first sign-in.
* The identity key is ``(organization_id, entra_tenant_id, entra_object_id)``, unique
  for bound rows; at most one pending invitation per email in an organisation/tenant.

Existing users keep their access: ``is_active = true`` becomes ``active`` and
``false`` becomes ``deactivated``. Review the user list after upgrading, because
users created by the previous just-in-time provisioning are carried over as active.

Revision ID: 7c1f4b2a9d30
Revises: e909d56fd80f
Create Date: 2026-10-05 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1f4b2a9d30"
down_revision: str | None = "e909d56fd80f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "status IN ('pending', 'active', 'suspended', 'deactivated')"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("status", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("first_name", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("last_name", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("invitation_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("created_by_id", sa.Uuid(), nullable=True))

    op.execute(
        "UPDATE users SET status = CASE WHEN is_active THEN 'active' ELSE 'deactivated' END, "
        "activated_at = created_at, "
        "deactivated_at = CASE WHEN is_active THEN NULL ELSE updated_at END"
    )

    with op.batch_alter_table("users") as batch:
        batch.alter_column("status", existing_type=sa.String(length=20), nullable=False)
        batch.alter_column("entra_object_id", existing_type=sa.String(length=64), nullable=True)
        batch.drop_constraint("uq_users_org_oid", type_="unique")
        batch.drop_column("is_active")
        batch.create_foreign_key(op.f("fk_users_created_by_id_users"), "users", ["created_by_id"], ["id"])
        batch.create_check_constraint(op.f("ck_users_status"), _STATUSES)
        batch.create_check_constraint(
            op.f("ck_users_identity_bound"), "entra_object_id IS NOT NULL OR status IN ('pending', 'deactivated')"
        )

    op.create_index(
        "uq_users_identity",
        "users",
        ["organization_id", "entra_tenant_id", "entra_object_id"],
        unique=True,
        postgresql_where=sa.text("entra_object_id IS NOT NULL"),
        sqlite_where=sa.text("entra_object_id IS NOT NULL"),
    )
    op.create_index(
        "uq_users_pending_email",
        "users",
        ["organization_id", "entra_tenant_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_users_org_status", "users", ["organization_id", "status"])


def downgrade() -> None:
    # Unredeemed invitations have no Entra identity and cannot exist in the previous schema.
    op.execute("DELETE FROM users WHERE entra_object_id IS NULL")
    op.drop_index("ix_users_org_status", table_name="users")
    op.drop_index("uq_users_pending_email", table_name="users")
    op.drop_index("uq_users_identity", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=True))
    op.execute("UPDATE users SET is_active = (status = 'active')")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=False)
        batch.drop_constraint(op.f("ck_users_identity_bound"), type_="check")
        batch.drop_constraint(op.f("ck_users_status"), type_="check")
        batch.drop_constraint(op.f("fk_users_created_by_id_users"), type_="foreignkey")
        batch.alter_column("entra_object_id", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint("uq_users_org_oid", ["organization_id", "entra_object_id"])
        for column in (
            "created_by_id",
            "deactivated_at",
            "activated_at",
            "invitation_expires_at",
            "invited_at",
            "last_name",
            "first_name",
            "status",
        ):
            batch.drop_column(column)
