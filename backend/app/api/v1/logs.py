"""Log Analytics / Application Insights queries.

Authorisation model:

* the target must be a discovered, non-deleted resource in the caller's organisation
* predefined queries require ``logs:view``; free-form KQL additionally requires ``logs:run_kql``
* free-form KQL is validated by ``kql_guard`` and executed resource-centric, so Azure
  scopes it to that resource's data
* custom queries are audited (query text truncated) and rate limited per user
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.api.deps import Azure, CurrentUser, DbSession, enforce_kql_rate_limit, require
from app.core.config import get_settings
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import Permission
from app.models import Resource
from app.schemas.misc import LogQueryIn, LogQueryOut, LogTarget, PredefinedQuery
from app.services.audit import record_audit
from app.services.azure.types import TimeRange
from app.services.kql_guard import apply_filters, validate_kql
from app.services.monitors.base import LogQueryDef
from app.services.monitors.registry import get_monitor, type_display_name
from app.services.relations import related_resource, resource_in_org, tenant_for_resource
from app.services.views import load_lookups

router = APIRouter(prefix="/logs", tags=["logs"])

LogViewer = Annotated[CurrentUser, Depends(require(Permission.view_logs))]

_WORKSPACE_TYPE = "microsoft.operationalinsights/workspaces"
_WORKSPACE_QUERIES = (
    LogQueryDef(
        "workspace_tables",
        "Tables with data",
        "union withsource = TableName *\n| summarize Rows = count() by TableName\n| order by Rows desc",
        category="Workspace",
    ),
    LogQueryDef(
        "workspace_errors",
        "Recent errors (AzureDiagnostics)",
        "AzureDiagnostics\n| where Level in~ ('Error', 'Critical') or Status_s == 'Failed'\n"
        "| project TimeGenerated, ResourceId, Category, OperationName, Level\n"
        "| order by TimeGenerated desc\n| take 500",
        severity_column="Level",
        category="Workspace",
    ),
    LogQueryDef(
        "workspace_activity",
        "Azure activity",
        "AzureActivity\n| project TimeGenerated, OperationNameValue, ActivityStatusValue, ResourceGroup, "
        "_ResourceId\n| order by TimeGenerated desc\n| take 500",
        category="Workspace",
    ),
)


def _queries_for(resource: Resource) -> tuple[LogQueryDef, ...]:
    if resource.resource_type == _WORKSPACE_TYPE:
        return _WORKSPACE_QUERIES
    return get_monitor(resource.monitor_key).log_queries


async def _target(db: DbSession, user: CurrentUser, resource_id: uuid.UUID) -> Resource:
    resource = await resource_in_org(db, user.organization_id, resource_id)
    if resource is None:
        raise NotFoundError("Resource not found.")
    return resource


@router.get("/targets", response_model=list[LogTarget])
async def log_targets(db: DbSession, user: LogViewer) -> list[LogTarget]:
    resources = [
        r
        for r in await db.scalars(
            select(Resource)
            .where(Resource.organization_id == user.organization_id, Resource.deleted_at.is_(None))
            .order_by(Resource.name)
        )
        if _queries_for(r)
    ]
    lookups = await load_lookups(db, user.organization_id, resources)
    return [
        LogTarget(
            resource_id=r.id,
            name=r.name,
            resource_type=r.resource_type,
            type_display_name=type_display_name(r.resource_type, r.monitor_key),
            project_id=r.project_id,
            environment_id=r.environment_id,
            project_name=lookups.projects[r.project_id].name if r.project_id in lookups.projects else None,
            environment_name=lookups.environments[r.environment_id].name
            if r.environment_id in lookups.environments
            else None,
            query_count=len(_queries_for(r)),
        )
        for r in resources
    ]


@router.get("/queries", response_model=list[PredefinedQuery])
async def predefined_queries(resource_id: uuid.UUID, db: DbSession, user: LogViewer) -> list[PredefinedQuery]:
    resource = await _target(db, user, resource_id)
    return [
        PredefinedQuery(
            key=q.key,
            title=q.title,
            description=q.description,
            category=q.category,
            kql=q.kql,
            visualization=q.visualization,
            target=q.target,
            supports_severity=bool(q.severity_column),
        )
        for q in _queries_for(resource)
    ]


@router.post("/query", response_model=LogQueryOut)
async def run_query(
    body: LogQueryIn,
    request: Request,
    db: DbSession,
    azure: Azure,
    user: LogViewer,
) -> LogQueryOut:
    resource = await _target(db, user, body.resource_id)
    time_range = TimeRange.from_params(body.time_range, body.start, body.end)
    execute_on = resource
    severity_column: str | None = None
    visualization = "table"

    if body.query_key:
        definition = next((q for q in _queries_for(resource) if q.key == body.query_key), None)
        if definition is None:
            raise NotFoundError("Unknown query for this resource.", code="QUERY_NOT_FOUND")
        base_query = definition.kql
        severity_column = definition.severity_column
        visualization = definition.visualization
        if definition.target != "self":
            related = await related_resource(db, resource, definition.target.split(":", 1)[1])
            if related is None:
                raise NotFoundError(
                    "The linked resource for this query has not been discovered "
                    "(for example, no Application Insights component is linked).",
                    code="RELATED_RESOURCE_NOT_FOUND",
                )
            execute_on = related
    elif body.kql:
        if not user.has(Permission.run_kql):
            await record_audit(
                db,
                action="logs.kql_denied",
                user=user,
                result="denied",
                request=request,
                target_type="resource",
                target_id=resource.azure_id,
            )
            await db.commit()
            raise PermissionDeniedError("Running custom KQL requires the Operator role or higher.")
        await enforce_kql_rate_limit(user)
        base_query = validate_kql(body.kql)
        await record_audit(
            db,
            action="logs.kql_executed",
            user=user,
            target_type="resource",
            target_id=resource.azure_id,
            request=request,
            details={"query": base_query[:500]},
        )
        await db.commit()
    else:
        raise ValidationFailedError("Provide either query_key or kql.")

    query = apply_filters(base_query, body.search, body.severities, severity_column)
    tenant = await tenant_for_resource(db, execute_on)
    result = await azure.logs.query_resource(
        tenant, execute_on.azure_id, query, time_range, get_settings().log_query_max_rows
    )
    return LogQueryOut(
        resource_id=resource.id,
        executed_against=execute_on.id,
        query=query,
        columns=[{"name": c.name, "type": c.type} for c in result.columns],
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        partial_error=result.partial_error,
        visualization=visualization,
        is_mock=result.is_mock,
        start=time_range.start,
        end=time_range.end,
    )
