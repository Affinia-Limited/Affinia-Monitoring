"""Archiving Azure connections, and removing leftover demo connections.

Disconnecting never changes anything in Azure: the connection, its subscriptions, discovered
resources and their dashboards are soft-deleted (``deleted_at``) so audit history stays intact.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, AzureConnection, Dashboard, Resource, Subscription
from app.services.alerts.evaluator import resolve_open_alerts
from app.services.audit import record_audit
from app.services.azure.mock.estate import MOCK_TENANT_ID

if TYPE_CHECKING:
    from app.api.deps import CurrentUser

logger = logging.getLogger(__name__)


def is_demo_connection(connection: AzureConnection) -> bool:
    """Connections to the built-in demo estate (only usable with ``AZURE_PROVIDER=mock``)."""
    return connection.tenant_id.lower() == MOCK_TENANT_ID


async def disconnect(
    db: AsyncSession,
    connection: AzureConnection,
    *,
    user: CurrentUser | None = None,
    request: Request | None = None,
    reason: str | None = None,
) -> int:
    """Archives the connection and everything discovered through it. Returns the resources archived."""
    now = datetime.now(UTC)
    connection.deleted_at = now
    connection.status = "disabled"
    for sub in await db.scalars(select(Subscription).where(Subscription.connection_id == connection.id)):
        sub.deleted_at = now
    resource_ids = []
    for resource in await db.scalars(
        select(Resource).where(Resource.connection_id == connection.id, Resource.deleted_at.is_(None))
    ):
        resource.deleted_at = now
        resource_ids.append(resource.id)
    if resource_ids:
        for dashboard in await db.scalars(select(Dashboard).where(Dashboard.resource_id.in_(resource_ids))):
            dashboard.deleted_at = now
        await resolve_open_alerts(
            db,
            connection.organization_id,
            Alert.resource_id.in_(resource_ids),
            "Closed: the resource's Azure connection was removed.",
        )
    details: dict[str, object] = {"name": connection.name, "resources_archived": len(resource_ids)}
    if reason:
        details["reason"] = reason
    await record_audit(
        db,
        action="azure.connection.disconnected",
        user=user,
        organization_id=connection.organization_id,
        actor=None if user else "system",
        target_type="azure_connection",
        target_id=str(connection.id),
        request=request,
        details=details,
    )
    return len(resource_ids)


async def archive_demo_connections(db: AsyncSession) -> int:
    """With real Azure, demo connections can never sync: archive them so demo data disappears."""
    demo = [
        c
        for c in await db.scalars(select(AzureConnection).where(AzureConnection.deleted_at.is_(None)))
        if is_demo_connection(c)
    ]
    for connection in demo:
        archived = await disconnect(db, connection, reason="Demo data removed: the platform uses real Azure")
        logger.info("demo_connection_archived", extra={"resources_archived": archived})
    return len(demo)
