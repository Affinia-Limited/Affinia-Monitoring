"""Alert templates: the recommended, tiered alert rules for each supported resource type.

A template is a monitor plugin's health rules (``app.services.monitors``), each with an
informational, a warning and a critical threshold. Values resolve in three layers:

1. the catalogue's recommendation (the monitor's ``HealthRule``)
2. the organisation's customisation (a ``HealthThreshold`` row; health status uses the same row)
3. the overrides of the assignment that covers a resource

Assignments apply templates to a resource, an environment, a project or the whole organisation.
A resource is covered by its most specific assignment (if that one is enabled): resource > environment > project >
organisation. Resources without a monitor (inventory items) have no template.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AlertTemplateAssignment, HealthThreshold, Resource
from app.services.monitors.base import AzureResourceMonitor, HealthRule
from app.services.monitors.registry import all_monitors, get_monitor
from app.services.views import UNMONITORED_KEYS

TIERS = ("info", "warning", "critical")
TIER_RANK = {"info": 1, "warning": 2, "critical": 3}
OVERRIDE_FIELDS = ("enabled", "info", "warning", "critical")
_DIRECTION = {"gt": "above", "gte": "at or above", "lt": "below", "lte": "at or below"}

#: Plain-language description of each template, shown when choosing what to apply.
_DESCRIPTIONS = {
    "app_service": "Web apps: plan CPU and memory, HTTP 5xx errors, response time and health checks.",
    "function_app": "Function apps: plan CPU and memory, HTTP 5xx errors, response time and health checks.",
    "app_service_plan": "App Service plans: CPU and memory pressure.",
    "app_insights": "Application Insights: availability tests, failed requests and server response time.",
    "front_door": "Front Door: 5xx rate, origin health and end-to-end latency.",
    "front_door_classic": "Front Door (classic): backend health and latency.",
    "sql_database": "SQL databases: CPU, DTU, storage, log IO, deadlocks, failed connections and availability.",
    "sql_elastic_pool": "SQL elastic pools: CPU and storage.",
    "storage_account": "Storage accounts: availability.",
    "key_vault": "Key Vault: availability and saturation.",
    "cosmos_db": "Cosmos DB: request unit consumption and availability.",
    "redis": "Azure Cache for Redis: server load and memory.",
    "virtual_machine": "Virtual machines: CPU and availability.",
    "aks": "AKS clusters: node CPU and memory.",
    "service_bus": "Service Bus: dead-lettered messages and server errors.",
    "event_hubs": "Event Hubs: throttled requests and server errors.",
    "application_gateway": "Application Gateway: unhealthy backend hosts and failed requests.",
    "load_balancer": "Load balancers: data path availability and health probe status.",
    "public_ip": "Public IP addresses: DDoS attack detection.",
}


@dataclass(frozen=True)
class EffectiveRule:
    """One template rule with every layer applied."""

    monitor_key: str
    metric: str
    label: str
    unit: str
    description: str
    operator: str
    reducer: str
    window_minutes: int
    frequency_minutes: int
    info: float | None
    warning: float | None
    critical: float | None
    default_info: float | None
    default_warning: float | None
    default_critical: float | None
    default_window_minutes: int
    enabled: bool
    #: The organisation customised this rule.
    customized: bool
    #: An assignment overrides this rule for the resource.
    overridden: bool = False

    @property
    def key(self) -> str:
        return f"{self.monitor_key}:{self.metric}"

    def threshold(self, tier: str) -> float | None:
        return {"info": self.info, "warning": self.warning, "critical": self.critical}[tier]

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "label": self.label,
            "unit": self.unit,
            "description": self.description,
            "operator": self.operator,
            "reducer": self.reducer,
            "window_minutes": self.window_minutes,
            "frequency_minutes": self.frequency_minutes,
            "info": self.info,
            "warning": self.warning,
            "critical": self.critical,
            "default_info": self.default_info,
            "default_warning": self.default_warning,
            "default_critical": self.default_critical,
            "default_window_minutes": self.default_window_minutes,
            "enabled": self.enabled,
            "customized": self.customized,
        }


# ---- catalogue -------------------------------------------------------------------------


def template_monitors() -> list[AzureResourceMonitor]:
    """Monitors that have a template (at least one health rule), in display order."""
    return sorted(
        (m for m in all_monitors() if m.health_rules and m.key not in UNMONITORED_KEYS),
        key=lambda m: (m.category, m.display_name),
    )


def template_monitor(monitor_key: str | None) -> AzureResourceMonitor | None:
    if not monitor_key or monitor_key in UNMONITORED_KEYS:
        return None
    monitor = get_monitor(monitor_key)
    return monitor if monitor.key == monitor_key and monitor.health_rules else None


def template_description(monitor: AzureResourceMonitor) -> str:
    return _DESCRIPTIONS.get(monitor.key) or f"Recommended alerts for {monitor.display_name}."


def known_rule(monitor_key: str, metric: str) -> HealthRule | None:
    monitor = template_monitor(monitor_key)
    if monitor is None:
        return None
    return next((r for r in monitor.health_rules if r.metric == metric), None)


async def load_customisations(db: AsyncSession, organization_id: uuid.UUID) -> dict[tuple[str, str], HealthThreshold]:
    rows = await db.scalars(select(HealthThreshold).where(HealthThreshold.organization_id == organization_id))
    return {(t.monitor_key, t.metric_name): t for t in rows}


def org_rules(
    monitor: AzureResourceMonitor, customisations: dict[tuple[str, str], HealthThreshold]
) -> list[EffectiveRule]:
    """A template's rules with the organisation's customisation applied."""
    out = []
    for rule in monitor.health_rules:
        definition = monitor.metric(rule.metric)
        row = customisations.get((monitor.key, rule.metric))
        out.append(
            EffectiveRule(
                monitor_key=monitor.key,
                metric=rule.metric,
                label=definition.label if definition else rule.metric,
                unit=definition.unit if definition else "",
                description=rule.description
                or (definition.description if definition else "")
                or (definition.label if definition else rule.metric),
                operator=rule.operator,
                reducer=rule.reducer,
                window_minutes=(row.window_minutes if row and row.window_minutes else rule.window_minutes),
                frequency_minutes=rule.frequency_minutes,
                info=row.info_threshold if row else rule.info,
                warning=row.warning_threshold if row else rule.warning,
                critical=row.critical_threshold if row else rule.critical,
                default_info=rule.info,
                default_warning=rule.warning,
                default_critical=rule.critical,
                default_window_minutes=rule.window_minutes,
                enabled=row.enabled if row else True,
                customized=row is not None,
            )
        )
    return out


def apply_overrides(rules: Iterable[EffectiveRule], overrides: dict[str, Any] | None) -> list[EffectiveRule]:
    """Apply an assignment's per-rule overrides (keys ``<monitor_key>:<metric>``)."""
    out = []
    for rule in rules:
        override = (overrides or {}).get(rule.key)
        if not isinstance(override, dict) or not override:
            out.append(rule)
            continue
        changes: dict[str, Any] = {"overridden": True}
        for name in OVERRIDE_FIELDS:
            if name in override:
                changes[name] = override[name] if name != "enabled" else bool(override[name])
        out.append(replace(rule, **changes))
    return out


# ---- tiers -----------------------------------------------------------------------------


def breaches(value: float, operator: str, threshold: float | None) -> bool:
    if threshold is None:
        return False
    return {
        "gt": value > threshold,
        "gte": value >= threshold,
        "lt": value < threshold,
        "lte": value <= threshold,
    }[operator]


def tier_for(value: float, rule: EffectiveRule) -> str | None:
    """The most severe tier the value crosses, or ``None`` below the informational threshold."""
    for tier in ("critical", "warning", "info"):
        if breaches(value, rule.operator, rule.threshold(tier)):
            return tier
    return None


def tier_order_error(operator: str, info: float | None, warning: float | None, critical: float | None) -> str | None:
    """A clear message when the tiers are out of order for the rule's direction, else ``None``."""
    present = [(name, value) for name, value in zip(TIERS, (info, warning, critical), strict=True) if value is not None]
    rising = operator in ("gt", "gte")
    for (low_name, low), (high_name, high) in pairwise(present):
        if (rising and not low < high) or (not rising and not low > high):
            sign = "<" if rising else ">"
            given = f"{low_name.capitalize()} {low:g}, {high_name.capitalize()} {high:g}"
            return (
                f"For '{_DIRECTION.get(operator, operator)}' rules the thresholds must be "
                f"Info {sign} Warning {sign} Critical ({given})."
            )
    return None


def validate_rule(rule: EffectiveRule) -> str | None:
    if not rule.enabled:
        return None
    if rule.info is None and rule.warning is None and rule.critical is None:
        return f"{rule.label}: an enabled rule needs at least one threshold."
    problem = tier_order_error(rule.operator, rule.info, rule.warning, rule.critical)
    return f"{rule.label}: {problem}" if problem else None


# ---- assignments -----------------------------------------------------------------------


def scope_key(
    resource_id: uuid.UUID | None, project_id: uuid.UUID | None, environment_id: uuid.UUID | None
) -> tuple[str, str]:
    """(scope, scope_key) for an assignment's columns."""
    if resource_id:
        return "resource", f"resource:{resource_id}"
    if environment_id:
        return "environment", f"environment:{environment_id}"
    if project_id:
        return "project", f"project:{project_id}"
    return "organization", "organization"


def scope_of(assignment: AlertTemplateAssignment) -> str:
    return scope_key(assignment.resource_id, assignment.project_id, assignment.environment_id)[0]


async def active_assignments(
    db: AsyncSession, organization_id: uuid.UUID, *, enabled_only: bool = False
) -> list[AlertTemplateAssignment]:
    """Non-deleted assignments. Disabled ones are included by default: a disabled assignment is an
    explicit "off" that overrides broader coverage (see ``covering_assignment``)."""
    query = select(AlertTemplateAssignment).where(
        AlertTemplateAssignment.organization_id == organization_id, AlertTemplateAssignment.deleted_at.is_(None)
    )
    if enabled_only:
        query = query.where(AlertTemplateAssignment.enabled.is_(True))
    return list(await db.scalars(query))


def covering_assignment(
    resource: Resource, assignments: Sequence[AlertTemplateAssignment]
) -> AlertTemplateAssignment | None:
    """The assignment that covers the resource, or ``None`` when it is not covered.

    The most specific assignment decides (resource > environment > project > organization). If that
    assignment is turned off, the resource is not covered, even when a broader assignment is on:
    "turn off for this resource / environment" must win over coverage applied higher up.
    """
    by_scope: dict[str, AlertTemplateAssignment] = {}
    for a in assignments:
        if a.deleted_at is not None:
            continue
        if a.resource_id:
            if a.resource_id == resource.id:
                by_scope["resource"] = a
        elif a.environment_id:
            if a.environment_id == resource.environment_id:
                by_scope["environment"] = a
        elif a.project_id:
            if a.project_id == resource.project_id:
                by_scope["project"] = a
        else:
            by_scope["organization"] = a
    for scope in ("resource", "environment", "project", "organization"):
        if scope in by_scope:
            decisive = by_scope[scope]
            return decisive if decisive.enabled else None
    return None


async def monitored_resources(db: AsyncSession, organization_id: uuid.UUID) -> list[Resource]:
    """Resources that have a template."""
    keys = [m.key for m in template_monitors()]
    return list(
        await db.scalars(
            select(Resource).where(
                Resource.organization_id == organization_id,
                Resource.deleted_at.is_(None),
                Resource.monitor_key.in_(keys),
            )
        )
    )


def resource_rules(
    resource: Resource,
    customisations: dict[tuple[str, str], HealthThreshold],
    assignment: AlertTemplateAssignment | None,
) -> list[EffectiveRule]:
    monitor = template_monitor(resource.monitor_key)
    if monitor is None:
        return []
    rules = org_rules(monitor, customisations)
    return apply_overrides(rules, assignment.overrides if assignment else None)


def fingerprint(resource_id: uuid.UUID, metric: str) -> str:
    return f"template:{resource_id}:{metric}"


def format_threshold(value: float, unit: str) -> str:
    text = f"{value:g}"
    return {
        "percent": f"{text}%",
        "milliseconds": f"{text} ms",
        "seconds": f"{text} s",
        "bytes": f"{text} bytes",
        "bytes_per_second": f"{text} bytes/s",
        "countps": f"{text}/s",
    }.get(unit, text)


def alert_title(rule: EffectiveRule, tier: str, resource_name: str) -> str:
    threshold = rule.threshold(tier)
    assert threshold is not None
    return f"{rule.label} {_DIRECTION[rule.operator]} {format_threshold(threshold, rule.unit)} on {resource_name}"
