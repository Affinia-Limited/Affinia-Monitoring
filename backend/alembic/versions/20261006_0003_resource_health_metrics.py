"""resources.health_metrics: latest health-rule metric readings for dashboards

Revision ID: 3d5e8a1c4b77
Revises: 7c1f4b2a9d30
Create Date: 2026-10-06 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3d5e8a1c4b77"
down_revision: str | None = "7c1f4b2a9d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    # Filled in by the next health evaluation (every HEALTH_INTERVAL_MINUTES).
    op.add_column("resources", sa.Column("health_metrics", _JSON, nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    op.drop_column("resources", "health_metrics")
