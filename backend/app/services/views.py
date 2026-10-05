"""Batch-loading helpers that turn ORM rows into API views without N+1 queries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, AlertRule, Dashboard, Environment, Project, Resource, Subscription
from app.schemas.alerts import AlertOut
from app.schemas.projects import HealthCounts
from app.schemas.resources import ResourceOut
from app.services.monitors.registry import get_monitor, type_display_name

HEALTH_RANK = {"critical": 3, "warning": 2, "healthy": 1, "unknown": 0}
OPEN_ALERT_STATUSES = ("active", "acknowledged")
#: Inventory-only resources (NICs, DNS zones, ...) have no monitoring signals and no health.
UNMONITORED_KEYS = (None, "generic")


def worst(statuses: Sequence[str]) -> str:
    if not statuses:
        return "unknown"
    top = max(statuses, key=lambda s: HEALTH_RANK.get(s, 0))
    if top == "unknown" and "healthy" in statuses:
        return "healthy"
    return top


def counts_for(statuses: Sequence[str]) -> HealthCounts:
    c = HealthCounts(total=len(statuses))
    for s in statuses:
        if s in ("healthy", "warning", "critical", "unknown"):
            setattr(c, s, getattr(c, s) + 1)
    return c


@dataclass
class Lookups:
    projects: dict[uuid.UUID, Project] = field(default_factory=dict)
    environments: dict[uuid.UUID, Environment] = field(default_factory=dict)
    subscriptions: dict[uuid.UUID, Subscription] = field(default_factory=dict)
    dashboards: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    alert_counts: dict[uuid.UUID, int] = field(default_factory=dict)


async def load_lookups(db: AsyncSession, organization_id: uuid.UUID, resources: Sequence[Resource]) -> Lookups:
    lk = Lookups()
    project_ids = {r.project_id for r in resources if r.project_id}
    env_ids = {r.environment_id for r in resources if r.environment_id}
    sub_ids = {r.subscription_ref_id for r in resources}
    if project_ids:
        lk.projects = {p.id: p for p in await db.scalars(select(Project).where(Project.id.in_(project_ids)))}
    if env_ids:
        lk.environments = {e.id: e for e in await db.scalars(select(Environment).where(Environment.id.in_(env_ids)))}
    if sub_ids:
        lk.subscriptions = {s.id: s for s in await db.scalars(select(Subscription).where(Subscription.id.in_(sub_ids)))}
    if resources:
        rows = await db.execute(
            select(Dashboard.resource_id, Dashboard.id).where(
                Dashboard.organization_id == organization_id,
                Dashboard.resource_id.in_([r.id for r in resources]),
                Dashboard.deleted_at.is_(None),
            )
        )
        lk.dashboards = {rid: did for rid, did in rows.all() if rid}
        counts = await db.execute(
            select(Alert.resource_id, func.count(Alert.id))
            .where(
                Alert.organization_id == organization_id,
                Alert.resource_id.in_([r.id for r in resources]),
                Alert.status.in_(OPEN_ALERT_STATUSES),
            )
            .group_by(Alert.resource_id)
        )
        lk.alert_counts = {rid: int(n) for rid, n in counts.all()}
    return lk


def resource_view(resource: Resource, lk: Lookups) -> ResourceOut:
    out = ResourceOut.model_validate(resource)
    project = lk.projects.get(resource.project_id) if resource.project_id else None
    env = lk.environments.get(resource.environment_id) if resource.environment_id else None
    sub = lk.subscriptions.get(resource.subscription_ref_id)
    out.project_name = project.name if project and project.deleted_at is None else None
    out.environment_name = env.name if env and env.deleted_at is None else None
    out.subscription_name = sub.display_name if sub else None
    out.type_display_name = type_display_name(resource.resource_type, resource.monitor_key)
    out.category = get_monitor(resource.monitor_key).category
    out.dashboard_id = lk.dashboards.get(resource.id)
    out.active_alerts = lk.alert_counts.get(resource.id, 0)
    return out


async def alert_views(db: AsyncSession, alerts: Sequence[Alert]) -> list[AlertOut]:
    resource_ids = {a.resource_id for a in alerts}
    resources = (
        {r.id: r for r in await db.scalars(select(Resource).where(Resource.id.in_(resource_ids)))}
        if resource_ids
        else {}
    )
    project_ids = {r.project_id for r in resources.values() if r.project_id}
    env_ids = {r.environment_id for r in resources.values() if r.environment_id}
    projects = (
        {p.id: p for p in await db.scalars(select(Project).where(Project.id.in_(project_ids)))} if project_ids else {}
    )
    envs = (
        {e.id: e for e in await db.scalars(select(Environment).where(Environment.id.in_(env_ids)))} if env_ids else {}
    )
    rule_ids = {a.rule_id for a in alerts if a.rule_id}
    rules = {r.id: r for r in await db.scalars(select(AlertRule).where(AlertRule.id.in_(rule_ids)))} if rule_ids else {}
    views = []
    for alert in alerts:
        out = AlertOut.model_validate(alert)
        rule = rules.get(alert.rule_id) if alert.rule_id else None
        definition = get_monitor(rule.monitor_key).metric(rule.metric_name) if rule else None
        out.unit = definition.unit if definition else None
        r = resources.get(alert.resource_id)
        if r:
            out.resource_name = r.name
            out.resource_type = r.resource_type
            out.type_display_name = type_display_name(r.resource_type, r.monitor_key)
            out.project_id, out.environment_id = r.project_id, r.environment_id
            out.project_name = projects[r.project_id].name if r.project_id in projects else None
            out.environment_name = envs[r.environment_id].name if r.environment_id in envs else None
        views.append(out)
    return views


async def active_alert_counts_by_project(db: AsyncSession, organization_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(Resource.project_id, func.count(Alert.id))
        .join(Resource, Resource.id == Alert.resource_id)
        .where(Alert.organization_id == organization_id, Alert.status.in_(OPEN_ALERT_STATUSES))
        .group_by(Resource.project_id)
    )
    return {pid: int(n) for pid, n in rows.all() if pid}


async def active_alert_counts_by_environment(
    db: AsyncSession, organization_id: uuid.UUID
) -> dict[tuple[uuid.UUID, uuid.UUID], int]:
    rows = await db.execute(
        select(Resource.project_id, Resource.environment_id, func.count(Alert.id))
        .join(Resource, Resource.id == Alert.resource_id)
        .where(Alert.organization_id == organization_id, Alert.status.in_(OPEN_ALERT_STATUSES))
        .group_by(Resource.project_id, Resource.environment_id)
    )
    return {(pid, eid): int(n) for pid, eid, n in rows.all() if pid and eid}


@dataclass
class ScopeHealth:
    """Health of the monitored resources in a project, environment or the whole organisation."""

    statuses: list[str] = field(default_factory=list)
    last_checked_at: datetime | None = None

    def add(self, status: str, checked_at: datetime | None) -> None:
        self.statuses.append(status)
        if checked_at and (self.last_checked_at is None or checked_at > self.last_checked_at):
            self.last_checked_at = checked_at

    @property
    def status(self) -> str:
        return worst(self.statuses)

    @property
    def counts(self) -> HealthCounts:
        return counts_for(self.statuses)


async def health_by_scope(
    db: AsyncSession, organization_id: uuid.UUID, project_ids: Sequence[uuid.UUID] | None = None
) -> dict[tuple[uuid.UUID, uuid.UUID | None], ScopeHealth]:
    """Monitored-resource health keyed by ``(project_id, environment_id)`` and ``(project_id, None)``."""
    query = select(
        Resource.project_id, Resource.environment_id, Resource.health_status, Resource.health_evaluated_at
    ).where(
        Resource.organization_id == organization_id,
        Resource.deleted_at.is_(None),
        Resource.project_id.is_not(None),
        Resource.monitor_key.is_not(None),
        Resource.monitor_key != "generic",
    )
    if project_ids is not None:
        query = query.where(Resource.project_id.in_(project_ids))
    scopes: dict[tuple[uuid.UUID, uuid.UUID | None], ScopeHealth] = {}
    for pid, eid, status, checked in (await db.execute(query)).all():
        scopes.setdefault((pid, None), ScopeHealth()).add(status, checked)
        if eid:
            scopes.setdefault((pid, eid), ScopeHealth()).add(status, checked)
    return scopes
