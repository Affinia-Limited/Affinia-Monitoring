"""Resolve relationships between discovered resources, always within one organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Resource
from app.services.monitors.registry import get_monitor


async def related_resource(db: AsyncSession, resource: Resource, relation: str) -> Resource | None:
    """E.g. ``app_service_plan`` for a site. Returns None if the related resource isn't discovered."""
    monitor = get_monitor(resource.monitor_key)
    target_id = monitor.related(resource.resource_type, resource.azure_id, resource.properties or {}).get(relation)
    if not target_id:
        return None
    return await db.scalar(
        select(Resource).where(
            Resource.organization_id == resource.organization_id,
            Resource.azure_id == target_id.lower(),
            Resource.deleted_at.is_(None),
        )
    )


async def related_resources(db: AsyncSession, resource: Resource, relation: str) -> list[Resource]:
    """One-to-many relations used by ``resource_table`` widgets."""
    base = select(Resource).where(Resource.organization_id == resource.organization_id, Resource.deleted_at.is_(None))
    if relation == "children":
        prefix = resource.azure_id.rstrip("/") + "/"
        rows = await db.scalars(base.where(Resource.azure_id.startswith(prefix, autoescape=True)))
        return [r for r in rows if r.monitor_key not in (None, "generic")]
    if relation == "apps_on_plan":
        rows = await db.scalars(base.where(Resource.resource_type == "microsoft.web/sites"))
        return [r for r in rows if (r.properties or {}).get("serverFarmId", "").lower() == resource.azure_id]
    single = await related_resource(db, resource, relation)
    return [single] if single else []


async def resource_in_org(db: AsyncSession, organization_id: uuid.UUID, resource_id: uuid.UUID) -> Resource | None:
    return await db.scalar(
        select(Resource).where(
            Resource.id == resource_id, Resource.organization_id == organization_id, Resource.deleted_at.is_(None)
        )
    )


async def tenant_for_resource(db: AsyncSession, resource: Resource) -> str:
    from app.models import AzureConnection

    tenant = await db.scalar(select(AzureConnection.tenant_id).where(AzureConnection.id == resource.connection_id))
    if tenant is None:  # pragma: no cover - FK guarantees this
        raise LookupError("connection not found")
    return tenant
