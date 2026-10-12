"""Export alerting rules as Azure Monitor ARM templates (see app.services.alerts.azure_export)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, DbSession, require
from app.core.permissions import Permission
from app.services.alerts.azure_export import action_group_name, build_export, parse_recipients
from app.services.audit import record_audit

router = APIRouter(prefix="/alert-rules", tags=["alerts"])

Manager = Annotated[CurrentUser, Depends(require(Permission.manage_alerts))]


@router.get("/azure-export")
async def azure_export(
    request: Request,
    db: DbSession,
    user: Manager,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    environment_id: Annotated[uuid.UUID | None, Query()] = None,
    resource_id: Annotated[uuid.UUID | None, Query()] = None,
    include_health: bool = True,
    include_rules: bool = True,
    covered_only: bool = False,
    recipients: Annotated[str | None, Query(max_length=13_000)] = None,
    action_group_name_: Annotated[str | None, Query(alias="action_group_name", max_length=260)] = None,
) -> dict[str, Any]:
    """Azure Monitor metric alerts and an email action group, one ARM template per subscription."""
    emails = parse_recipients(recipients)
    result = await build_export(
        db,
        user.organization_id,
        project_id=project_id,
        environment_id=environment_id,
        resource_id=resource_id,
        include_health=include_health,
        include_rules=include_rules,
        recipients=emails,
        group_name=action_group_name(action_group_name_),
        covered_only=covered_only,
        access=user.access,
    )
    # Counts only: recipient addresses are personal data and never written to the audit log.
    await record_audit(
        db,
        action="alerts.azure_exported",
        user=user,
        target_type="alert_rules",
        request=request,
        details={
            "project_id": str(project_id) if project_id else None,
            "environment_id": str(environment_id) if environment_id else None,
            "resource_id": str(resource_id) if resource_id else None,
            "include_health": include_health,
            "include_rules": include_rules,
            "covered_only": covered_only,
            "templates": len(result["templates"]),
            "alert_rules": sum(t["alert_count"] for t in result["templates"]),
            "resources": result["resources"],
            "skipped": len(result["skipped"]),
            "recipients": len(emails),
        },
    )
    await db.commit()
    return result
