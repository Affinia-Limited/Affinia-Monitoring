"""alert templates: informational tier and window on health_thresholds, template assignments

Revision ID: 4f7a2d9c6e18
Revises: 8e4a6c2f9b13
Create Date: 2026-10-12 10:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4f7a2d9c6e18"
down_revision: str | None = "8e4a6c2f9b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("health_thresholds", sa.Column("info_threshold", sa.Float(), nullable=True))
    op.add_column("health_thresholds", sa.Column("window_minutes", sa.Integer(), nullable=True))
    _backfill_info()

    op.create_table(
        "alert_template_assignments",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("overrides", _JSON, nullable=False),
        sa.Column("notification_channel_ids", _JSON, nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_alert_template_assignments_created_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name=op.f("fk_alert_template_assignments_environment_id_environments"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_alert_template_assignments_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_alert_template_assignments_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["resources.id"], name=op.f("fk_alert_template_assignments_resource_id_resources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_template_assignments")),
    )
    op.create_index(
        op.f("ix_alert_template_assignments_organization_id"),
        "alert_template_assignments",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_alert_template_assignments_deleted_at"), "alert_template_assignments", ["deleted_at"], unique=False
    )
    op.create_index(
        "uq_alert_template_assignments_scope",
        "alert_template_assignments",
        ["organization_id", "scope_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def _backfill_info() -> None:
    """Organisations that already customised a rule keep its recommended informational tier.

    A row is authoritative once it exists (a NULL info tier means "none"), so rows written before this
    column existed get the catalogue's recommendation rather than silently losing the tier.
    """
    from app.services.monitors.registry import all_monitors

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, monitor_key, metric_name FROM health_thresholds")).all()
    rules = {(m.key, r.metric): r.info for m in all_monitors() for r in m.health_rules}
    for row_id, monitor_key, metric_name in rows:
        info = rules.get((monitor_key, metric_name))
        if info is not None:
            bind.execute(
                sa.text("UPDATE health_thresholds SET info_threshold = :info WHERE id = :id"),
                {"info": info, "id": row_id},
            )


def downgrade() -> None:
    op.drop_index("uq_alert_template_assignments_scope", table_name="alert_template_assignments")
    op.drop_index(op.f("ix_alert_template_assignments_deleted_at"), table_name="alert_template_assignments")
    op.drop_index(op.f("ix_alert_template_assignments_organization_id"), table_name="alert_template_assignments")
    op.drop_table("alert_template_assignments")
    op.drop_column("health_thresholds", "window_minutes")
    op.drop_column("health_thresholds", "info_threshold")
