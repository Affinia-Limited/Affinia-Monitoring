"""Alert templates: the recommended alert rules per resource type, and where they apply.

* ``/alert-templates``: the catalogue with the organisation's customised thresholds
* ``/alert-template-assignments``: apply templates to a resource, environment, project or everything
* ``/resources/{id}/alert-plan``: what is monitored for one resource, and how it stands now
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, require, require_all_projects
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import Permission
from app.models import (
    Alert,
    AlertTemplateAssignment,
    Environment,
    HealthThreshold,
    NotificationChannel,
    Project,
    Resource,
)
from app.schemas.alert_templates import (
    AlertPlanOut,
    AlertTemplateOut,
    AssignmentIn,
    AssignmentOut,
    AssignmentUpdate,
    EffectiveCoverageOut,
    PlanRuleOut,
    RuleOverride,
    TemplateRuleIn,
    TemplateRuleOut,
)
from app.services.alerts.email_lists import EMAIL_CHANNEL
from app.services.alerts.evaluator import OPEN_STATUSES, resolve_uncovered_template_alerts
from app.services.alerts.templates import (
    EffectiveRule,
    active_assignments,
    covering_assignment,
    fingerprint,
    known_rule,
    load_customisations,
    monitored_resources,
    org_rules,
    resource_rules,
    scope_key,
    scope_of,
    template_description,
    template_monitor,
    template_monitors,
    tier_for,
    validate_rule,
)
from app.services.audit import record_audit
from app.services.monitors.base import AzureResourceMonitor

router = APIRouter(tags=["alert templates"])

Viewer = Annotated[CurrentUser, Depends(require(Permission.view_alerts))]
Manager = Annotated[CurrentUser, Depends(require(Permission.manage_alerts))]
#: Template defaults are organisation-wide: changing them needs access to all projects.
OrgManager = Annotated[CurrentUser, Depends(require_all_projects(Permission.manage_alerts))]


# ---- views ------------------------------------------------------------------------------


def _rule_out(rule: EffectiveRule) -> TemplateRuleOut:
    return TemplateRuleOut.model_validate(rule.as_dict())


async def _coverage(
    db: DbSession, user: CurrentUser
) -> tuple[list[Resource], list[AlertTemplateAssignment], dict[uuid.UUID, uuid.UUID]]:
    """The caller's monitored resources, enabled assignments, and resource id -> covering assignment id."""
    resources = [r for r in await monitored_resources(db, user.organization_id) if user.access.can_see_resource(r)]
    assignments = await active_assignments(db, user.organization_id)
    covering: dict[uuid.UUID, uuid.UUID] = {}
    for resource in resources:
        assignment = covering_assignment(resource, assignments)
        if assignment is not None:
            covering[resource.id] = assignment.id
    return resources, assignments, covering


def _template_out(
    monitor: AzureResourceMonitor,
    customisations: dict[tuple[str, str], HealthThreshold],
    resource_count: int,
    covered_count: int,
) -> AlertTemplateOut:
    rules = org_rules(monitor, customisations)
    return AlertTemplateOut(
        monitor_key=monitor.key,
        display_name=monitor.display_name,
        category=monitor.category,
        description=template_description(monitor),
        customized=any(r.customized for r in rules),
        resource_count=resource_count,
        covered_count=covered_count,
        rules=[_rule_out(r) for r in rules],
    )


async def _templates(db: DbSession, user: CurrentUser) -> dict[str, AlertTemplateOut]:
    """The catalogue; resource and coverage counts are over the caller's resources only."""
    customisations = await load_customisations(db, user.organization_id)
    resources, _, covering = await _coverage(db, user)
    totals = Counter(r.monitor_key for r in resources)
    covered = Counter(r.monitor_key for r in resources if r.id in covering)
    return {
        m.key: _template_out(m, customisations, totals.get(m.key, 0), covered.get(m.key, 0))
        for m in template_monitors()
    }


async def _assignment_views(
    db: DbSession, user: CurrentUser, assignments: list[AlertTemplateAssignment]
) -> list[AssignmentOut]:
    if not assignments:
        return []
    resources, _, covering = await _coverage(db, user)
    covered_by: dict[uuid.UUID, list[Resource]] = defaultdict(list)
    for resource in resources:
        if resource.id in covering:
            covered_by[covering[resource.id]].append(resource)
    names = await _names(db, assignments)
    out = []
    for a in assignments:
        mine = covered_by.get(a.id, []) if a.enabled else []
        out.append(
            AssignmentOut(
                id=a.id,
                scope=scope_of(a),  # type: ignore[arg-type]
                resource_id=a.resource_id,
                project_id=a.project_id,
                environment_id=a.environment_id,
                resource_name=names["resource"].get(a.resource_id) if a.resource_id else None,
                project_name=names["project"].get(a.project_id) if a.project_id else None,
                environment_name=names["environment"].get(a.environment_id) if a.environment_id else None,
                enabled=a.enabled,
                overrides=a.overrides or {},
                notification_channel_ids=[str(c) for c in a.notification_channel_ids or []],
                covered_resources=len(mine),
                templates=sorted({r.monitor_key for r in mine if r.monitor_key}),
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
        )
    return out


async def _names(db: DbSession, assignments: list[AlertTemplateAssignment]) -> dict[str, dict[Any, str]]:
    resource_ids = {a.resource_id for a in assignments if a.resource_id}
    project_ids = {a.project_id for a in assignments if a.project_id}
    env_ids = {a.environment_id for a in assignments if a.environment_id}
    return {
        "resource": {r.id: r.name for r in await db.scalars(select(Resource).where(Resource.id.in_(resource_ids)))}
        if resource_ids
        else {},
        "project": {p.id: p.name for p in await db.scalars(select(Project).where(Project.id.in_(project_ids)))}
        if project_ids
        else {},
        "environment": {e.id: e.name for e in await db.scalars(select(Environment).where(Environment.id.in_(env_ids)))}
        if env_ids
        else {},
    }


# ---- templates --------------------------------------------------------------------------


@router.get("/alert-templates", response_model=list[AlertTemplateOut])
async def list_templates(db: DbSession, user: Viewer) -> list[AlertTemplateOut]:
    return list((await _templates(db, user)).values())


def _monitor_or_404(monitor_key: str) -> AzureResourceMonitor:
    monitor = template_monitor(monitor_key)
    if monitor is None:
        raise NotFoundError("Alert template not found.")
    return monitor


@router.get("/alert-templates/{monitor_key}", response_model=AlertTemplateOut)
async def get_template(monitor_key: str, db: DbSession, user: Viewer) -> AlertTemplateOut:
    _monitor_or_404(monitor_key)
    return (await _templates(db, user))[monitor_key]


def _rule_of(
    monitor: AzureResourceMonitor, metric: str, customisations: dict[tuple[str, str], HealthThreshold]
) -> EffectiveRule:
    rule = next((r for r in org_rules(monitor, customisations) if r.metric == metric), None)
    if rule is None:
        raise NotFoundError("Template rule not found.")
    return rule


@router.put("/alert-templates/{monitor_key}/rules/{metric}", response_model=TemplateRuleOut)
async def customise_rule(
    monitor_key: str, metric: str, body: TemplateRuleIn, request: Request, db: DbSession, user: OrgManager
) -> TemplateRuleOut:
    """Set the organisation's thresholds for one template rule (health status follows warning/critical)."""
    monitor = _monitor_or_404(monitor_key)
    customisations = await load_customisations(db, user.organization_id)
    current = _rule_of(monitor, metric, customisations)
    proposed = EffectiveRule(
        **{
            **current.__dict__,
            "enabled": body.enabled,
            "info": body.info,
            "warning": body.warning,
            "critical": body.critical,
            "window_minutes": body.window_minutes or current.default_window_minutes,
        }
    )
    if problem := validate_rule(proposed):
        raise ValidationFailedError(problem)
    row = customisations.get((monitor.key, metric))
    if row is None:
        row = HealthThreshold(organization_id=user.organization_id, monitor_key=monitor.key, metric_name=metric)
        db.add(row)
    row.enabled = body.enabled
    row.info_threshold, row.warning_threshold, row.critical_threshold = body.info, body.warning, body.critical
    row.window_minutes = body.window_minutes
    await record_audit(
        db,
        action="alert_template.rule_customised",
        user=user,
        target_type="alert_template",
        target_id=f"{monitor.key}:{metric}",
        request=request,
        details=body.model_dump(),
    )
    await db.commit()
    return _rule_out(_rule_of(monitor, metric, {(monitor.key, metric): row}))


@router.delete("/alert-templates/{monitor_key}/rules/{metric}", response_model=TemplateRuleOut)
async def reset_rule(
    monitor_key: str, metric: str, request: Request, db: DbSession, user: OrgManager
) -> TemplateRuleOut:
    """Back to the recommended thresholds (for alerts and health status)."""
    monitor = _monitor_or_404(monitor_key)
    if known_rule(monitor.key, metric) is None:
        raise NotFoundError("Template rule not found.")
    customisations = await load_customisations(db, user.organization_id)
    row = customisations.pop((monitor.key, metric), None)
    if row is not None:
        await db.delete(row)
        await record_audit(
            db,
            action="alert_template.rule_reset",
            user=user,
            target_type="alert_template",
            target_id=f"{monitor.key}:{metric}",
            request=request,
        )
        await db.commit()
    return _rule_out(_rule_of(monitor, metric, {}))


# ---- assignments ------------------------------------------------------------------------


async def _validate_overrides(
    db: DbSession, user: CurrentUser, overrides: dict[str, RuleOverride]
) -> dict[str, dict[str, Any]]:
    customisations = await load_customisations(db, user.organization_id)
    clean: dict[str, dict[str, Any]] = {}
    for key, override in overrides.items():
        monitor_key, _, metric = key.partition(":")
        monitor = template_monitor(monitor_key)
        if monitor is None or known_rule(monitor_key, metric) is None:
            raise ValidationFailedError(f"Unknown template rule '{key}'. Use '<resource type>:<metric>'.")
        values = override.model_dump(exclude_unset=True)
        if values.get("enabled", True) is None:
            values.pop("enabled")  # null means "keep the organisation's setting"
        if not values:
            continue
        current = _rule_of(monitor, metric, customisations)
        merged = EffectiveRule(**{**current.__dict__, **values})
        if problem := validate_rule(merged):
            raise ValidationFailedError(problem)
        clean[key] = values
    return clean


async def _validate_channels(db: DbSession, user: CurrentUser, channel_ids: list[uuid.UUID]) -> list[str]:
    wanted = set(channel_ids)
    if not wanted:
        return []
    found = set(
        await db.scalars(
            select(NotificationChannel.id).where(
                NotificationChannel.id.in_(wanted),
                NotificationChannel.organization_id == user.organization_id,
                NotificationChannel.deleted_at.is_(None),
                NotificationChannel.channel_type != EMAIL_CHANNEL,
            )
        )
    )
    if found != wanted:
        raise ValidationFailedError(
            "Choose notification channels from Alerts > Notification channels or Microsoft Teams. "
            "Email lists receive alerts automatically."
        )
    return [str(c) for c in channel_ids]


async def _scope_ids(
    db: DbSession, user: CurrentUser, body: AssignmentIn
) -> tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
    org = user.organization_id
    if body.resource_id:
        resource = await db.scalar(
            select(Resource).where(
                Resource.id == body.resource_id, Resource.organization_id == org, Resource.deleted_at.is_(None)
            )
        )
        if resource is None or not user.access.can_see_resource(resource):
            raise NotFoundError("Resource not found.")
        if template_monitor(resource.monitor_key) is None:
            raise ValidationFailedError("This resource type has no alert template (inventory items are not monitored).")
        return resource.id, None, None
    if body.environment_id:
        if not body.project_id:
            raise ValidationFailedError("Choose the project of the environment.")
        env = await db.scalar(
            select(Environment).where(
                Environment.id == body.environment_id,
                Environment.organization_id == org,
                Environment.deleted_at.is_(None),
            )
        )
        if env is None or env.project_id != body.project_id or not user.access.can_see_environment(env.id):
            raise ValidationFailedError("The environment must belong to the chosen project.")
        if not user.access.has_full_environment(env.id):
            raise PermissionDeniedError(
                "You need access to the whole environment to apply alerts to it.", code="ACCESS_OUT_OF_SCOPE"
            )
        return None, body.project_id, env.id
    if body.project_id:
        found = await db.scalar(
            select(Project.id).where(
                Project.id == body.project_id, Project.organization_id == org, Project.deleted_at.is_(None)
            )
        )
        if found is None or not user.access.can_see_project(found):
            raise NotFoundError("Project not found.")
        if not user.access.has_full_project(found):
            raise PermissionDeniedError(
                "You need access to the whole project to apply alerts to it.", code="ACCESS_OUT_OF_SCOPE"
            )
        return None, body.project_id, None
    # Organisation-wide coverage.
    user.access.require_unrestricted()
    return None, None, None


async def _assignment(db: DbSession, user: CurrentUser, assignment_id: uuid.UUID) -> AlertTemplateAssignment:
    assignment = await db.scalar(
        select(AlertTemplateAssignment).where(
            AlertTemplateAssignment.id == assignment_id,
            AlertTemplateAssignment.organization_id == user.organization_id,
            AlertTemplateAssignment.deleted_at.is_(None),
        )
    )
    if assignment is None or not await _assignment_in_scope(db, user, assignment):
        raise NotFoundError("Alert template assignment not found.")
    return assignment


async def _assignment_in_scope(db: DbSession, user: CurrentUser, assignment: AlertTemplateAssignment) -> bool:
    """Coverage is the caller's when its whole scope is: its resource, environment or project, or
    (organisation-wide coverage) access to all projects."""
    if user.access.unrestricted:
        return True
    if assignment.resource_id is not None:
        resource = await db.get(Resource, assignment.resource_id)
        return resource is not None and user.access.can_see_resource(resource)
    return user.access.covers_scope(project_id=assignment.project_id, environment_id=assignment.environment_id)


def _check_channels_allowed(user: CurrentUser, requested: list[uuid.UUID], existing: list[Any] | None = None) -> None:
    """Notification channels are organisation settings: scoped managers keep existing ones only."""
    if user.access.unrestricted:
        return
    if {str(c) for c in requested} - {str(c) for c in existing or []}:
        user.access.require_unrestricted()


def _audit_details(a: AlertTemplateAssignment) -> dict[str, Any]:
    return {
        "scope": scope_of(a),
        "resource_id": str(a.resource_id) if a.resource_id else None,
        "project_id": str(a.project_id) if a.project_id else None,
        "environment_id": str(a.environment_id) if a.environment_id else None,
        "enabled": a.enabled,
        "overrides": a.overrides or {},
        "notification_channels": len(a.notification_channel_ids or []),
    }


@router.get("/alert-template-assignments", response_model=list[AssignmentOut])
async def list_assignments(
    db: DbSession,
    user: Viewer,
    resource_id: Annotated[uuid.UUID | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    environment_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[AssignmentOut]:
    query = select(AlertTemplateAssignment).where(
        AlertTemplateAssignment.organization_id == user.organization_id,
        AlertTemplateAssignment.deleted_at.is_(None),
    )
    if resource_id:
        query = query.where(AlertTemplateAssignment.resource_id == resource_id)
    if project_id:
        query = query.where(AlertTemplateAssignment.project_id == project_id)
    if environment_id:
        query = query.where(AlertTemplateAssignment.environment_id == environment_id)
    assignments = [
        a
        for a in await db.scalars(query.order_by(AlertTemplateAssignment.created_at))
        if await _assignment_in_scope(db, user, a)
    ]
    return await _assignment_views(db, user, assignments)


@router.get("/alert-template-assignments/effective", response_model=EffectiveCoverageOut)
async def effective_coverage(
    db: DbSession, user: Viewer, environment_id: Annotated[uuid.UUID, Query()]
) -> EffectiveCoverageOut:
    """The coverage that decides for an environment: its own, else its project's, else organisation-wide.

    Members see which broader coverage applies to their environment (its label only); the coverage
    itself is returned only when it lies within their access.
    """
    env = await db.scalar(
        select(Environment).where(
            Environment.id == environment_id,
            Environment.organization_id == user.organization_id,
            Environment.deleted_at.is_(None),
        )
    )
    if env is None or not user.access.can_see_environment(env.id):
        raise NotFoundError("Environment not found.")
    candidates = list(
        await db.scalars(
            select(AlertTemplateAssignment).where(
                AlertTemplateAssignment.organization_id == user.organization_id,
                AlertTemplateAssignment.deleted_at.is_(None),
                AlertTemplateAssignment.resource_id.is_(None),
            )
        )
    )
    decisive = (
        next((a for a in candidates if a.environment_id == env.id), None)
        or next((a for a in candidates if a.environment_id is None and a.project_id == env.project_id), None)
        or next((a for a in candidates if a.environment_id is None and a.project_id is None), None)
    )
    if decisive is None:
        return EffectiveCoverageOut(scope=None, covered=False, label=None, assignment=None)
    project = await db.get(Project, env.project_id)
    project_name = project.name if project else "Project"
    if decisive.environment_id:
        scope, label = "environment", f"{project_name} / {env.name}"
    elif decisive.project_id:
        scope, label = "project", f"{project_name} (all environments)"
    else:
        scope, label = "organization", "All projects"
    visible = await _assignment_in_scope(db, user, decisive)
    view = (await _assignment_views(db, user, [decisive]))[0] if visible else None
    return EffectiveCoverageOut(scope=scope, covered=decisive.enabled, label=label, assignment=view)


@router.post("/alert-template-assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
async def create_assignment(body: AssignmentIn, request: Request, db: DbSession, user: Manager) -> AssignmentOut:
    resource_id, project_id, environment_id = await _scope_ids(db, user, body)
    _check_channels_allowed(user, body.notification_channel_ids)
    overrides = await _validate_overrides(db, user, body.overrides)
    channel_ids = await _validate_channels(db, user, body.notification_channel_ids)
    _, key = scope_key(resource_id, project_id, environment_id)
    existing = await db.scalar(
        select(AlertTemplateAssignment.id).where(
            AlertTemplateAssignment.organization_id == user.organization_id,
            AlertTemplateAssignment.scope_key == key,
            AlertTemplateAssignment.deleted_at.is_(None),
        )
    )
    if existing is not None:
        raise _exists(existing)
    assignment = AlertTemplateAssignment(
        organization_id=user.organization_id,
        scope_key=key,
        resource_id=resource_id,
        project_id=project_id,
        environment_id=environment_id,
        enabled=body.enabled,
        overrides=overrides,
        notification_channel_ids=channel_ids,
        created_by_id=user.id,
    )
    try:
        async with db.begin_nested():
            db.add(assignment)
            await db.flush()
    except IntegrityError:
        # A concurrent request created the same scope first.
        raced = await db.scalar(
            select(AlertTemplateAssignment.id).where(
                AlertTemplateAssignment.organization_id == user.organization_id,
                AlertTemplateAssignment.scope_key == key,
                AlertTemplateAssignment.deleted_at.is_(None),
            )
        )
        raise _exists(raced) from None
    await record_audit(
        db,
        action="alert_template_assignment.created",
        user=user,
        target_type="alert_template_assignment",
        target_id=str(assignment.id),
        request=request,
        details=_audit_details(assignment),
    )
    await db.commit()
    await db.refresh(assignment)
    return (await _assignment_views(db, user, [assignment]))[0]


def _exists(existing: uuid.UUID | None) -> ConflictError:
    return ConflictError(
        "Alert templates are already applied at this scope. Edit that assignment instead.",
        code="ASSIGNMENT_EXISTS",
        details={"id": str(existing) if existing else None},
    )


@router.patch("/alert-template-assignments/{assignment_id}", response_model=AssignmentOut)
async def update_assignment(
    assignment_id: uuid.UUID, body: AssignmentUpdate, request: Request, db: DbSession, user: Manager
) -> AssignmentOut:
    assignment = await _assignment(db, user, assignment_id)
    if body.enabled is not None:
        assignment.enabled = body.enabled
    if body.overrides is not None:
        assignment.overrides = await _validate_overrides(db, user, body.overrides)
    if body.notification_channel_ids is not None:
        _check_channels_allowed(user, body.notification_channel_ids, assignment.notification_channel_ids)
        assignment.notification_channel_ids = await _validate_channels(db, user, body.notification_channel_ids)
    await db.flush()
    if not assignment.enabled:
        await resolve_uncovered_template_alerts(db, user.organization_id)
    await record_audit(
        db,
        action="alert_template_assignment.updated",
        user=user,
        target_type="alert_template_assignment",
        target_id=str(assignment.id),
        request=request,
        details=_audit_details(assignment),
    )
    await db.commit()
    await db.refresh(assignment)
    return (await _assignment_views(db, user, [assignment]))[0]


@router.delete(
    "/alert-template-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_assignment(assignment_id: uuid.UUID, request: Request, db: DbSession, user: Manager) -> None:
    assignment = await _assignment(db, user, assignment_id)
    assignment.deleted_at = datetime.now(UTC)
    await db.flush()
    await resolve_uncovered_template_alerts(db, user.organization_id)
    await record_audit(
        db,
        action="alert_template_assignment.deleted",
        user=user,
        target_type="alert_template_assignment",
        target_id=str(assignment.id),
        request=request,
        details=_audit_details(assignment),
    )
    await db.commit()


# ---- one resource -----------------------------------------------------------------------


@router.get("/resources/{resource_id}/alert-plan", response_model=AlertPlanOut)
async def alert_plan(resource_id: uuid.UUID, db: DbSession, user: Viewer) -> AlertPlanOut:
    """The template rules that apply to a resource, with effective values and where each stands now."""
    resource = await db.scalar(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.organization_id == user.organization_id,
            Resource.deleted_at.is_(None),
        )
    )
    if resource is None or not user.access.can_see_resource(resource):
        raise NotFoundError("Resource not found.")
    monitor = template_monitor(resource.monitor_key)
    if monitor is None:
        return AlertPlanOut(
            resource_id=resource.id, monitor_key=resource.monitor_key, template=None, assignment=None, rules=[]
        )
    templates = await _templates(db, user)
    assignments = await active_assignments(db, user.organization_id)
    assignment = covering_assignment(resource, assignments)
    customisations = await load_customisations(db, user.organization_id)
    open_alerts = {
        a.fingerprint: a
        for a in await db.scalars(
            select(Alert).where(
                Alert.organization_id == user.organization_id,
                Alert.resource_id == resource.id,
                Alert.source == "template",
                Alert.status.in_(OPEN_STATUSES),
            )
        )
    }
    readings = {r.get("metric"): r for r in resource.health_metrics or []}
    rules = []
    for rule in resource_rules(resource, customisations, assignment):
        alert = open_alerts.get(fingerprint(resource.id, rule.metric))
        value: float | None
        if alert is not None:
            value, tier = alert.current_value, alert.severity
        elif (reading := readings.get(rule.metric)) and reading.get("value") is not None:
            value = float(reading["value"])
            tier = tier_for(value, rule) or "ok"
        else:
            value, tier = None, "unknown"
        rules.append(
            PlanRuleOut(
                **_rule_out(rule).model_dump(), current_value=value, current_tier=tier, overridden=rule.overridden
            )
        )
    assignment_view = (
        (await _assignment_views(db, user, [assignment]))[0]
        if assignment is not None and await _assignment_in_scope(db, user, assignment)
        else None
    )
    return AlertPlanOut(
        resource_id=resource.id,
        monitor_key=resource.monitor_key,
        template=templates[monitor.key],
        assignment=assignment_view,
        rules=rules,
    )
