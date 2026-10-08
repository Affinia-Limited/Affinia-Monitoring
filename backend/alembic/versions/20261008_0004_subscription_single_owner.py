"""subscriptions: an Azure subscription is actively connected to at most one organisation

Revision ID: 5b2c9e7d1f40
Revises: 3d5e8a1c4b77
Create Date: 2026-10-08 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b2c9e7d1f40"
down_revision: str | None = "3d5e8a1c4b77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    shared = op.get_bind().execute(
        sa.text(
            "SELECT subscription_id FROM subscriptions WHERE deleted_at IS NULL "
            "GROUP BY subscription_id HAVING COUNT(DISTINCT organization_id) > 1"
        )
    ).scalars().all()
    if shared:
        # Two organisations reading the same subscription is a data-isolation problem: an operator must
        # decide which one owns it (disconnect it from the other) before this migration can run.
        raise RuntimeError(
            "Subscriptions connected to more than one organisation: " + ", ".join(shared)
            + ". Disconnect each from all but its owning organisation, then run the migration again."
        )
    op.create_index(
        "uq_subscriptions_active_subscription",
        "subscriptions",
        ["subscription_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_subscriptions_active_subscription", table_name="subscriptions")
