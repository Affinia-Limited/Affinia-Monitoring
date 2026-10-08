"""reliability: one open alert per condition, one active sync per connection, sync heartbeats, indexes

Revision ID: 8e4a6c2f9b13
Revises: 5b2c9e7d1f40
Create Date: 2026-10-08 14:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e4a6c2f9b13"
down_revision: str | None = "5b2c9e7d1f40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN_ALERT = "status IN ('active', 'acknowledged')"
_ACTIVE_RUN = "status IN ('queued', 'running')"


def upgrade() -> None:
    op.add_column("sync_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))

    # Duplicates created by overlapping jobs before these constraints existed: keep one, close the rest.
    op.execute(
        f"""
        UPDATE alerts SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
        WHERE {_OPEN_ALERT} AND CAST(id AS TEXT) NOT IN (
            SELECT MIN(CAST(a2.id AS TEXT)) FROM alerts a2
            WHERE a2.status IN ('active', 'acknowledged')
            GROUP BY a2.organization_id, a2.fingerprint
        )
        """
    )
    op.execute(
        f"""
        UPDATE sync_runs SET status = 'failed', error_code = 'SUPERSEDED', finished_at = CURRENT_TIMESTAMP
        WHERE {_ACTIVE_RUN} AND CAST(id AS TEXT) NOT IN (
            SELECT MIN(CAST(s2.id AS TEXT)) FROM sync_runs s2
            WHERE s2.status IN ('queued', 'running')
            GROUP BY s2.connection_id
        )
        """
    )

    op.create_index(
        "uq_alerts_open_fingerprint",
        "alerts",
        ["organization_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text(_OPEN_ALERT),
        sqlite_where=sa.text(_OPEN_ALERT),
    )
    op.create_index(
        "uq_sync_runs_active_connection",
        "sync_runs",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_RUN),
        sqlite_where=sa.text(_ACTIVE_RUN),
    )
    op.create_index("ix_alerts_org_started", "alerts", ["organization_id", "started_at"])
    op.create_index("ix_alerts_rule_id", "alerts", ["rule_id"])
    op.create_index("ix_resources_environment", "resources", ["environment_id"])


def downgrade() -> None:
    op.drop_index("ix_resources_environment", table_name="resources")
    op.drop_index("ix_alerts_rule_id", table_name="alerts")
    op.drop_index("ix_alerts_org_started", table_name="alerts")
    op.drop_index("uq_sync_runs_active_connection", table_name="sync_runs")
    op.drop_index("uq_alerts_open_fingerprint", table_name="alerts")
    op.drop_column("sync_runs", "heartbeat_at")
