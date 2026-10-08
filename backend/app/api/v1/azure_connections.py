from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import Azure, CurrentUser, DbSession, require
from app.core.config import Environment as AppEnvironment
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import Permission
from app.models import AzureConnection, Environment, Organization, Project, Resource, Subscription, SyncRun
from app.schemas.azure import (
    ConnectionCreated,
    ConnectionIn,
    ConnectionOut,
    ConnectionUpdate,
    PlatformIdentityOut,
    SubscriptionOut,
    SyncRunOut,
)
from app.schemas.common import column_values
from app.services.audit import record_audit
from app.services.connections import disconnect, is_demo_connection
from app.services.discovery import queue_sync_run
from app.services.jobs import enqueue_sync

router = APIRouter(prefix="/azure", tags=["azure"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_resources))]
Connector = Annotated[CurrentUser, Depends(require(Permission.connect_azure))]
Syncer = Annotated[CurrentUser, Depends(require(Permission.sync_azure))]

REQUIRED_ROLES = [
    {
        "role": "Reader",
        "scope": "Subscription or resource group",
        "purpose": "Resource discovery (Resource Graph) and resource metadata",
    },
    {
        "role": "Monitoring Reader",
        "scope": "Subscription or resource group",
        "purpose": "Azure Monitor metrics, alerts and Resource Health",
    },
    {
        "role": "Log Analytics Reader",
        "scope": "Log Analytics workspaces / Application Insights",
        "purpose": "Log queries and Application Insights telemetry",
    },
]


@router.get("/identity", response_model=PlatformIdentityOut)
async def platform_identity(user: Connector, azure: Azure) -> PlatformIdentityOut:
    settings = get_settings()
    methods = ["managed_identity", "workload_identity"]
    if settings.environment is AppEnvironment.development:
        methods.append("developer")
    return PlatformIdentityOut(
        provider=settings.azure_provider.value,
        auth_methods=methods,
        client_id=settings.azure_client_id,
        home_tenant_id=settings.azure_tenant_id,
        required_roles=REQUIRED_ROLES,
        is_mock=azure.is_mock,
    )


@router.get("/available-subscriptions", response_model=list[dict[str, str]])
async def available_subscriptions(
    db: DbSession, user: Connector, azure: Azure, tenant_id: Annotated[str, Query(pattern=r"^[0-9a-fA-F-]{36}$")]
) -> list[dict[str, str]]:
    """Subscriptions the platform identity can read in a tenant that this organisation may connect."""
    subs = await azure.resource_graph.list_subscriptions(tenant_id.lower())
    allowed = await _allowed_azure_tenants(db, user, azure)
    elsewhere = await _connected_elsewhere(db, user, [s.subscription_id for s in subs])
    return [
        {"subscription_id": s.subscription_id, "display_name": s.display_name, "state": s.state}
        for s in subs
        if (allowed is None or s.tenant_id.lower() in allowed) and s.subscription_id.lower() not in elsewhere
    ]


async def _connection_view(db: DbSession, connection: AzureConnection) -> ConnectionOut:
    subs = list(
        await db.scalars(
            select(Subscription).where(Subscription.connection_id == connection.id, Subscription.deleted_at.is_(None))
        )
    )
    latest = await db.scalar(
        select(SyncRun).where(SyncRun.connection_id == connection.id).order_by(SyncRun.created_at.desc()).limit(1)
    )
    count = await db.scalar(
        select(func.count(Resource.id)).where(Resource.connection_id == connection.id, Resource.deleted_at.is_(None))
    )
    out = ConnectionOut.model_validate(column_values(connection))
    out.is_demo = is_demo_connection(connection)
    out.subscriptions = [SubscriptionOut.model_validate(s) for s in subs]
    out.resource_count = int(count or 0)
    out.latest_run = SyncRunOut.model_validate(latest) if latest else None
    return out


async def _get_connection(db: DbSession, user: CurrentUser, connection_id: uuid.UUID) -> AzureConnection:
    connection = await db.scalar(
        select(AzureConnection).where(
            AzureConnection.id == connection_id,
            AzureConnection.organization_id == user.organization_id,
            AzureConnection.deleted_at.is_(None),
        )
    )
    if connection is None:
        raise NotFoundError("Azure connection not found.")
    return connection


async def _validate_defaults(
    db: DbSession, user: CurrentUser, project_id: uuid.UUID | None, env_id: uuid.UUID | None
) -> None:
    if project_id:
        project = await db.scalar(
            select(Project.id).where(
                Project.id == project_id, Project.organization_id == user.organization_id, Project.deleted_at.is_(None)
            )
        )
        if project is None:
            raise ValidationFailedError("The default project was not found.")
    if env_id:
        env = await db.scalar(
            select(Environment).where(
                Environment.id == env_id,
                Environment.organization_id == user.organization_id,
                Environment.deleted_at.is_(None),
            )
        )
        if env is None or (project_id and env.project_id != project_id):
            raise ValidationFailedError("The default environment must belong to the default project.")


async def _allowed_azure_tenants(db: DbSession, user: CurrentUser, azure: Azure) -> set[str] | None:
    """Home tenants whose subscriptions this organisation may connect; ``None`` means any (demo data only).

    The platform identity can often read many organisations' subscriptions (e.g. every customer that
    delegated access through Lighthouse), so being readable is not proof of ownership.
    """
    if azure.is_mock:
        return None
    org_tenant = await db.scalar(select(Organization.entra_tenant_id).where(Organization.id == user.organization_id))
    allowed = {t.lower() for t in get_settings().organization_azure_tenants.get(org_tenant or "", [])}
    if org_tenant:
        allowed.add(org_tenant.lower())
    return allowed


async def _connected_elsewhere(db: DbSession, user: CurrentUser, subscription_ids: list[str]) -> set[str]:
    rows = await db.scalars(
        select(Subscription.subscription_id).where(
            Subscription.organization_id != user.organization_id,
            Subscription.subscription_id.in_([s.lower() for s in subscription_ids]),
            Subscription.deleted_at.is_(None),
        )
    )
    return {r.lower() for r in rows}


async def _check_subscriptions_free(
    db: DbSession, user: CurrentUser, azure: Azure, tenant_id: str, subscription_ids: list[str]
) -> None:
    taken = list(
        await db.scalars(
            select(Subscription.subscription_id).where(
                Subscription.organization_id == user.organization_id,
                Subscription.subscription_id.in_(subscription_ids),
                Subscription.deleted_at.is_(None),
            )
        )
    )
    if taken:
        raise ConflictError(
            "Some subscriptions are already connected.",
            code="SUBSCRIPTION_ALREADY_CONNECTED",
            details={"subscription_ids": taken},
        )
    # A subscription belongs to one organisation. Which one is not disclosed.
    elsewhere = await _connected_elsewhere(db, user, subscription_ids)
    if elsewhere:
        raise ConflictError(
            "Some subscriptions are connected to another organisation.",
            code="SUBSCRIPTION_OWNED_ELSEWHERE",
            details={"subscription_ids": sorted(elsewhere)},
        )
    allowed = await _allowed_azure_tenants(db, user, azure)
    if allowed is None:
        return
    refused = []
    for sub_id in subscription_ids:
        info = await azure.resource_graph.get_subscription(tenant_id, sub_id)
        if info.tenant_id.lower() not in allowed:
            refused.append(sub_id)
    if refused:
        raise PermissionDeniedError(
            "These subscriptions belong to an Azure tenant your organisation is not approved for. "
            "A platform operator can approve it (ORGANIZATION_AZURE_TENANTS).",
            code="SUBSCRIPTION_TENANT_NOT_ALLOWED",
            details={"subscription_ids": refused},
        )


async def _attach_subscription(db: DbSession, user: CurrentUser, connection: AzureConnection, sub_id: str) -> None:
    """Reuse a previously disconnected subscription row so its resources keep their history."""
    previous = await db.scalar(
        select(Subscription).where(
            Subscription.organization_id == user.organization_id, Subscription.subscription_id == sub_id
        )
    )
    if previous is not None:
        previous.connection_id, previous.tenant_id, previous.deleted_at = connection.id, connection.tenant_id, None
        return
    db.add(
        Subscription(
            organization_id=user.organization_id,
            connection_id=connection.id,
            subscription_id=sub_id,
            tenant_id=connection.tenant_id,
        )
    )


async def _queue_run(db: DbSession, connection: AzureConnection, trigger: str, user: CurrentUser) -> SyncRun:
    run, _ = await queue_sync_run(db, connection, trigger, user.id)
    return run


@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(db: DbSession, user: Viewer) -> list[ConnectionOut]:
    connections = await db.scalars(
        select(AzureConnection)
        .where(AzureConnection.organization_id == user.organization_id, AzureConnection.deleted_at.is_(None))
        .order_by(AzureConnection.created_at)
    )
    return [await _connection_view(db, c) for c in connections]


@router.post("/connections", response_model=ConnectionCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_connection(
    body: ConnectionIn, request: Request, db: DbSession, azure: Azure, user: Connector
) -> ConnectionCreated:
    if body.auth_method == "developer" and get_settings().environment is not AppEnvironment.development:
        raise ValidationFailedError("Developer credentials can only be used in local development.")
    await _validate_defaults(db, user, body.default_project_id, body.default_environment_id)
    await _check_subscriptions_free(db, user, azure, body.tenant_id, body.subscription_ids)

    connection = AzureConnection(
        organization_id=user.organization_id,
        name=body.name,
        tenant_id=body.tenant_id,
        auth_method=body.auth_method,
        status="pending",
        default_project_id=body.default_project_id,
        default_environment_id=body.default_environment_id,
        created_by_id=user.id,
    )
    db.add(connection)
    await db.flush()
    for sub_id in body.subscription_ids:
        await _attach_subscription(db, user, connection, sub_id)
    run = await _queue_run(db, connection, "initial", user)
    await record_audit(
        db,
        action="azure.connection.created",
        user=user,
        target_type="azure_connection",
        target_id=str(connection.id),
        request=request,
        details={"name": body.name, "tenant_id": body.tenant_id, "subscription_ids": body.subscription_ids},
    )
    await db.commit()
    enqueue_sync(str(run.id))
    return ConnectionCreated(connection=await _connection_view(db, connection), sync_run=SyncRunOut.model_validate(run))


@router.get("/connections/{connection_id}", response_model=ConnectionOut)
async def get_connection(connection_id: uuid.UUID, db: DbSession, user: Viewer) -> ConnectionOut:
    return await _connection_view(db, await _get_connection(db, user, connection_id))


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: uuid.UUID, body: ConnectionUpdate, request: Request, db: DbSession, azure: Azure, user: Connector
) -> ConnectionOut:
    connection = await _get_connection(db, user, connection_id)
    changes = body.model_dump(exclude_unset=True)
    project_id = changes.get("default_project_id", connection.default_project_id)
    env_id = changes.get("default_environment_id", connection.default_environment_id)
    await _validate_defaults(db, user, project_id, env_id)
    if body.add_subscription_ids:
        await _check_subscriptions_free(db, user, azure, connection.tenant_id, body.add_subscription_ids)
        for sub_id in body.add_subscription_ids:
            await _attach_subscription(db, user, connection, sub_id)
    for field in ("name", "sync_enabled", "default_project_id", "default_environment_id"):
        if field in changes:
            setattr(connection, field, changes[field])
    await record_audit(
        db,
        action="azure.connection.updated",
        user=user,
        target_type="azure_connection",
        target_id=str(connection.id),
        request=request,
        details={"fields": sorted(changes)},
    )
    await db.commit()
    return await _connection_view(db, connection)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_connection(connection_id: uuid.UUID, request: Request, db: DbSession, user: Connector) -> None:
    connection = await _get_connection(db, user, connection_id)
    await disconnect(db, connection, user=user, request=request)
    await db.commit()


@router.post("/connections/{connection_id}/sync", response_model=SyncRunOut, status_code=status.HTTP_202_ACCEPTED)
async def sync_connection(connection_id: uuid.UUID, request: Request, db: DbSession, user: Syncer) -> SyncRun:
    connection = await _get_connection(db, user, connection_id)
    run, created = await queue_sync_run(db, connection, "manual", user.id)
    if not created:
        await db.commit()
        return run
    await record_audit(
        db,
        action="azure.sync.started",
        user=user,
        target_type="azure_connection",
        target_id=str(connection.id),
        request=request,
    )
    await db.commit()
    enqueue_sync(str(run.id))
    return run


@router.post("/sync", response_model=list[SyncRunOut], status_code=status.HTTP_202_ACCEPTED)
async def sync_all(request: Request, db: DbSession, user: Syncer) -> list[SyncRun]:
    connections = list(
        await db.scalars(
            select(AzureConnection).where(
                AzureConnection.organization_id == user.organization_id, AzureConnection.deleted_at.is_(None)
            )
        )
    )
    runs, queued = [], []
    for connection in connections:
        run, created = await queue_sync_run(db, connection, "manual", user.id)
        runs.append(run)
        if created:
            queued.append(str(run.id))
    await record_audit(
        db,
        action="azure.sync.started",
        user=user,
        target_type="organization",
        target_id=str(user.organization_id),
        request=request,
        details={"connections": len(connections)},
    )
    await db.commit()
    for run_id in queued:
        enqueue_sync(run_id)
    return runs


@router.get("/sync-runs/{run_id}", response_model=SyncRunOut)
async def get_sync_run(run_id: uuid.UUID, db: DbSession, user: Viewer) -> SyncRun:
    run = await db.scalar(select(SyncRun).where(SyncRun.id == run_id, SyncRun.organization_id == user.organization_id))
    if run is None:
        raise NotFoundError("Sync run not found.")
    return run


@router.get("/connections/{connection_id}/sync-runs", response_model=list[SyncRunOut])
async def list_sync_runs(connection_id: uuid.UUID, db: DbSession, user: Viewer) -> list[SyncRun]:
    connection = await _get_connection(db, user, connection_id)
    return list(
        await db.scalars(
            select(SyncRun).where(SyncRun.connection_id == connection.id).order_by(SyncRun.created_at.desc()).limit(20)
        )
    )


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(db: DbSession, user: Viewer) -> list[Subscription]:
    return list(
        await db.scalars(
            select(Subscription)
            .where(Subscription.organization_id == user.organization_id, Subscription.deleted_at.is_(None))
            .order_by(Subscription.display_name)
        )
    )
