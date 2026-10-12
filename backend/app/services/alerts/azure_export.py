"""Export the platform's alerting rules as Azure Monitor ARM templates.

The export turns two sources into native Azure Monitor metric alerts, so Azure itself evaluates
them and emails an action group even when this platform is down:

* the health rules of each resource's monitor plugin, with the organisation's threshold overrides
  (one warning and one critical alert per rule, where that threshold exists)
* the organisation's enabled custom alert rules, for the resources in their scope

One template is produced per Azure subscription. Deploy it at resource-group scope in any resource
group of that subscription (metric alerts are global resources that point at their target by id).
Names are deterministic, so deploying an updated export again updates the alerts in place.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.models import AlertRule, Environment, HealthThreshold, Project, Resource, Subscription
from app.services.monitors.base import MetricDef, Rollup
from app.services.monitors.registry import get_monitor
from app.services.relations import related_resource
from app.services.views import UNMONITORED_KEYS

DEFAULT_ACTION_GROUP = "amp-alerts"
MAX_RECIPIENTS = 50
ACTION_GROUP_API = "2023-01-01"
METRIC_ALERT_API = "2018-03-01"
TEMPLATE_SCHEMA = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
TAGS = {"managed-by": "azure-monitoring-platform"}

#: Azure's allowed metric alert window sizes, in minutes.
_WINDOWS = (
    (1, "PT1M"),
    (5, "PT5M"),
    (15, "PT15M"),
    (30, "PT30M"),
    (60, "PT1H"),
    (360, "PT6H"),
    (720, "PT12H"),
    (1440, "PT24H"),
)
_FREQUENCY_MINUTES = {"PT1M": 1, "PT5M": 5, "PT15M": 15, "PT30M": 30, "PT1H": 60}
_OPERATOR_WORDS = {"gt": "above", "gte": "at or above", "lt": "below", "lte": "at or below"}
_OPERATORS = {"gt": "GreaterThan", "gte": "GreaterThanOrEqual", "lt": "LessThan", "lte": "LessThanOrEqual"}
_REDUCER_AGGREGATION: dict[str, str] = {"avg": "Average", "sum": "Total", "max": "Maximum", "min": "Minimum"}
#: Metric aggregation -> the reducer that combines it without changing its meaning.
_NATURAL: dict[tuple[str, str], str] = {
    ("Average", "avg"): "Average",
    ("Total", "sum"): "Total",
    ("Maximum", "max"): "Maximum",
    ("Minimum", "min"): "Minimum",
    ("Count", "sum"): "Count",
}
_SEVERITY = {"critical": 0, "error": 1, "warning": 2, "info": 3}
_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
#: Characters Azure does not allow in metric alert names, plus control characters.
_BAD_NAME_CHARS = re.compile(r"[*<>%&:\\?+/#\x00-\x1f\x7f]")
_MAX_NAME = 260


def parse_recipients(raw: str | None) -> list[str]:
    """Comma, semicolon or newline separated addresses: validated, lower-cased, de-duplicated."""
    if not raw:
        return []
    values = [v.strip().lower() for v in re.split(r"[,;\s]+", raw) if v.strip()]
    recipients = list(dict.fromkeys(values))
    invalid = [v for v in recipients if len(v) > 254 or not _EMAIL.match(v)]
    if invalid:
        # Never echo submitted values back.
        raise ValidationFailedError(
            f"{len(invalid)} recipient address{'es are' if len(invalid) != 1 else ' is'} not a valid email address.",
            code="INVALID_RECIPIENTS",
        )
    if len(recipients) > MAX_RECIPIENTS:
        raise ValidationFailedError(f"At most {MAX_RECIPIENTS} recipients are supported.", code="TOO_MANY_RECIPIENTS")
    return recipients


def action_group_name(raw: str | None) -> str:
    """Letters, digits, '-', '_', '.' and spaces; anything else becomes '-'."""
    name = re.sub(r"[^A-Za-z0-9 ._-]", "-", (raw or "").strip()).strip(" .-")[:_MAX_NAME]
    return name or DEFAULT_ACTION_GROUP


def short_name(name: str) -> str:
    """Action group short name: up to 12 letters, digits, '-' or '_' (shown in SMS and email)."""
    return (re.sub(r"[^A-Za-z0-9_-]", "", name)[:12]) or "amp-alerts"


def window_size(minutes: int) -> str | None:
    return next((iso for m, iso in _WINDOWS if m >= minutes), None)


def evaluation_frequency(window: str) -> str:
    window_minutes = next(m for m, iso in _WINDOWS if iso == window)
    if window_minutes <= 5:
        frequency = "PT1M"
    elif window_minutes <= 30:
        frequency = "PT5M"
    elif window_minutes <= 360:
        frequency = "PT15M"
    else:
        frequency = "PT1H"
    # The frequency may never exceed the window.
    return frequency if _FREQUENCY_MINUTES[frequency] <= window_minutes else window


def time_aggregation(definition: MetricDef, reducer: Rollup) -> str:
    return _NATURAL.get((definition.aggregation, reducer)) or _REDUCER_AGGREGATION[reducer]


def _slug(value: str, limit: int = 60) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")[:limit] or "rule"


def _clean_name(value: str) -> str:
    return _BAD_NAME_CHARS.sub("-", value).strip(" .")[:_MAX_NAME]


@dataclass
class _Candidate:
    """One alert to emit: a metric threshold on one resource."""

    resource: Resource
    metric_key: str
    operator: str
    threshold: float
    severity: int
    window_minutes: int
    aggregation: str | None  # custom rules carry their own; health rules derive it
    reducer: Rollup
    suffix: str
    rule_label: str
    origin: str


@dataclass
class _Template:
    subscription_id: str
    subscription_name: str
    alerts: list[dict[str, Any]] = field(default_factory=list)
    names: set[str] = field(default_factory=set)


async def _scope(
    db: AsyncSession,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    environment_id: uuid.UUID | None,
    resource_id: uuid.UUID | None,
) -> None:
    if project_id and not await db.scalar(
        select(Project.id).where(
            Project.id == project_id, Project.organization_id == organization_id, Project.deleted_at.is_(None)
        )
    ):
        raise NotFoundError("Project not found.")
    if environment_id:
        env = await db.scalar(
            select(Environment).where(
                Environment.id == environment_id,
                Environment.organization_id == organization_id,
                Environment.deleted_at.is_(None),
            )
        )
        if env is None:
            raise NotFoundError("Environment not found.")
        if project_id and env.project_id != project_id:
            raise ValidationFailedError("The environment does not belong to the selected project.")
    if resource_id and not await db.scalar(
        select(Resource.id).where(
            Resource.id == resource_id, Resource.organization_id == organization_id, Resource.deleted_at.is_(None)
        )
    ):
        raise NotFoundError("Resource not found.")


def _rule_applies(rule: AlertRule, resource: Resource) -> bool:
    return (
        rule.monitor_key == resource.monitor_key
        and (rule.resource_id is None or rule.resource_id == resource.id)
        and (rule.project_id is None or rule.project_id == resource.project_id)
        and (rule.environment_id is None or rule.environment_id == resource.environment_id)
    )


def _candidates(
    resource: Resource,
    overrides: dict[tuple[str, str], HealthThreshold],
    rules: list[AlertRule],
    include_health: bool,
    include_rules: bool,
) -> list[_Candidate]:
    monitor = get_monitor(resource.monitor_key)
    out: list[_Candidate] = []
    if include_health:
        for rule in monitor.health_rules:
            override = overrides.get((monitor.key, rule.metric))
            if override is not None and not override.enabled:
                continue
            warning = override.warning_threshold if override else rule.warning
            critical = override.critical_threshold if override else rule.critical
            for level, threshold in (("warning", warning), ("critical", critical)):
                if threshold is None:
                    continue
                out.append(
                    _Candidate(
                        resource=resource,
                        metric_key=rule.metric,
                        operator=rule.operator,
                        threshold=threshold,
                        severity=_SEVERITY[level],
                        window_minutes=rule.window_minutes,
                        aggregation=None,
                        reducer=rule.reducer,
                        suffix=level,
                        rule_label=f"Health threshold ({level})",
                        origin=f"{level.capitalize()} health threshold"
                        + (" (organisation override)" if override else ""),
                    )
                )
    if include_rules:
        for custom in rules:
            if not _rule_applies(custom, resource):
                continue
            out.append(
                _Candidate(
                    resource=resource,
                    metric_key=custom.metric_name,
                    operator=custom.operator,
                    threshold=custom.threshold,
                    severity=_SEVERITY.get(custom.severity, 2),
                    window_minutes=custom.window_minutes,
                    aggregation=custom.aggregation,
                    reducer="avg",
                    suffix=f"{_slug(custom.name, 40)}-{str(custom.id)[:8]}",
                    rule_label=f"Alert rule '{custom.name}'",
                    origin=f"Custom alert rule '{custom.name}'",
                )
            )
    return out


def _alert_name(template: _Template, candidate: _Candidate, target: Resource) -> str:
    base = _clean_name(f"amp-{candidate.resource.name}-{candidate.metric_key}-{candidate.suffix}")
    if base not in template.names:
        return base
    # Two resources with the same name (different resource groups): add a stable hash of the target.
    digest = hashlib.sha256(f"{target.azure_id}|{candidate.metric_key}|{candidate.suffix}".encode()).hexdigest()[:8]
    return _clean_name(f"{base[: _MAX_NAME - 9]}-{digest}")


def _metric_alert(name: str, candidate: _Candidate, definition: MetricDef, target: Resource) -> dict[str, Any]:
    window_minutes = max(candidate.window_minutes, definition.min_interval_minutes or 0)
    window = window_size(window_minutes)
    assert window is not None  # checked by the caller
    aggregation = candidate.aggregation or time_aggregation(definition, candidate.reducer)
    threshold = candidate.threshold / (definition.scale or 1.0)
    via = "" if target.id == candidate.resource.id else f" (measured on {target.name})"
    split = f" Azure alerts on the total across '{definition.split_by}'." if definition.split_by else ""
    action_group = "[resourceId('Microsoft.Insights/actionGroups', parameters('actionGroupName'))]"
    properties: dict[str, Any] = {
        "description": (
            f"{candidate.origin}: {definition.label}{via} {_OPERATOR_WORDS[candidate.operator]} "
            f"{candidate.threshold:g} {definition.unit} on {candidate.resource.name}. "
            f"Exported from the Azure Monitoring Platform.{split}"
        )[:2048],
        "severity": candidate.severity,
        "enabled": "[parameters('alertsEnabled')]",
        "scopes": [target.azure_id],
        "evaluationFrequency": evaluation_frequency(window),
        "windowSize": window,
        "targetResourceType": target.resource_type,
        "criteria": {
            "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
            "allOf": [
                {
                    "criterionType": "StaticThresholdCriterion",
                    "name": "Metric1",
                    "metricName": definition.name,
                    "metricNamespace": definition.namespace or target.resource_type,
                    "operator": _OPERATORS[candidate.operator],
                    "threshold": round(threshold, 9),
                    "timeAggregation": aggregation,
                    "dimensions": [],
                    "skipMetricValidation": False,
                }
            ],
        },
        "autoMitigate": True,
        "actions": [{"actionGroupId": action_group}],
    }
    if target.location:
        properties["targetResourceRegion"] = target.location
    return {
        "type": "Microsoft.Insights/metricAlerts",
        "apiVersion": METRIC_ALERT_API,
        "name": name,
        "location": "global",
        "tags": TAGS,
        "dependsOn": [action_group],
        "properties": properties,
    }


def _arm_template(template: _Template, group_name: str, recipients: list[str]) -> dict[str, Any]:
    receivers_copy = {
        "name": "emailReceivers",
        "count": "[length(parameters('emailReceivers'))]",
        "input": {
            "name": "[concat('email-', copyIndex('emailReceivers'))]",
            "emailAddress": "[parameters('emailReceivers')[copyIndex('emailReceivers')]]",
            "useCommonAlertSchema": True,
        },
    }
    return {
        "$schema": TEMPLATE_SCHEMA,
        "contentVersion": "1.0.0.0",
        "metadata": {
            "generator": "azure-monitoring-platform",
            "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "subscriptionId": template.subscription_id,
            "description": "Azure Monitor metric alerts exported from the Azure Monitoring Platform. Deploy "
            "into any resource group of this subscription.",
        },
        "parameters": {
            "actionGroupName": {
                "type": "string",
                "defaultValue": group_name,
                "metadata": {"description": "Action group that receives every alert in this template."},
            },
            "actionGroupShortName": {
                "type": "string",
                "defaultValue": short_name(group_name),
                "maxLength": 12,
                "metadata": {"description": "Shown in alert emails (12 characters at most)."},
            },
            "emailReceivers": {
                "type": "array",
                "defaultValue": recipients,
                "metadata": {"description": "Email addresses notified when an alert fires or resolves."},
            },
            "alertsEnabled": {
                "type": "bool",
                "defaultValue": True,
                "metadata": {"description": "Deploy the alert rules enabled."},
            },
        },
        "resources": [
            {
                "type": "Microsoft.Insights/actionGroups",
                "apiVersion": ACTION_GROUP_API,
                "name": "[parameters('actionGroupName')]",
                "location": "Global",
                "tags": TAGS,
                "properties": {
                    "groupShortName": "[parameters('actionGroupShortName')]",
                    "enabled": True,
                    "copy": [receivers_copy],
                },
            },
            *template.alerts,
        ],
        "outputs": {
            "actionGroupId": {
                "type": "string",
                "value": "[resourceId('Microsoft.Insights/actionGroups', parameters('actionGroupName'))]",
            },
            "alertRuleCount": {"type": "int", "value": len(template.alerts)},
        },
    }


async def build_export(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
    environment_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    include_health: bool = True,
    include_rules: bool = True,
    recipients: list[str] | None = None,
    group_name: str = DEFAULT_ACTION_GROUP,
) -> dict[str, Any]:
    await _scope(db, organization_id, project_id, environment_id, resource_id)
    query = select(Resource).where(
        Resource.organization_id == organization_id,
        Resource.deleted_at.is_(None),
        Resource.monitor_key.is_not(None),
        Resource.monitor_key.notin_([k for k in UNMONITORED_KEYS if k]),
    )
    if project_id:
        query = query.where(Resource.project_id == project_id)
    if environment_id:
        query = query.where(Resource.environment_id == environment_id)
    if resource_id:
        query = query.where(Resource.id == resource_id)
    resources = list(await db.scalars(query.order_by(Resource.name, Resource.azure_id)))

    overrides = {
        (t.monitor_key, t.metric_name): t
        for t in await db.scalars(select(HealthThreshold).where(HealthThreshold.organization_id == organization_id))
    }
    rules = (
        list(
            await db.scalars(
                select(AlertRule)
                .where(
                    AlertRule.organization_id == organization_id,
                    AlertRule.deleted_at.is_(None),
                    AlertRule.enabled.is_(True),
                )
                .order_by(AlertRule.name, AlertRule.id)
            )
        )
        if include_rules
        else []
    )
    subscriptions = {
        s.id: s
        for s in await db.scalars(
            select(Subscription).where(Subscription.id.in_({r.subscription_ref_id for r in resources}))
        )
    }

    templates: dict[str, _Template] = {}
    skipped: list[dict[str, str]] = []
    related_cache: dict[tuple[uuid.UUID, str], Resource | None] = {}
    covered: set[uuid.UUID] = set()
    for resource in resources:
        monitor = get_monitor(resource.monitor_key)
        for candidate in _candidates(resource, overrides, rules, include_health, include_rules):
            definition = monitor.metric(candidate.metric_key)
            if definition is None or not definition.name:
                skipped.append(
                    {
                        "resource_name": resource.name,
                        "rule": candidate.rule_label,
                        "reason": f"Metric '{candidate.metric_key}' has no Azure Monitor metric to alert on.",
                    }
                )
                continue
            if candidate.operator not in _OPERATORS:
                skipped.append(
                    {"resource_name": resource.name, "rule": candidate.rule_label, "reason": "Unsupported operator."}
                )
                continue
            target: Resource = resource
            if definition.target != "self":
                relation = definition.target.split(":", 1)[1]
                key = (resource.id, relation)
                if key not in related_cache:
                    related_cache[key] = await related_resource(db, resource, relation)
                found = related_cache[key]
                if found is None:
                    skipped.append(
                        {
                            "resource_name": resource.name,
                            "rule": f"{candidate.rule_label}: {definition.label}",
                            "reason": f"{definition.label} is measured on the related "
                            f"{relation.replace('_', ' ')}, which has not been discovered.",
                        }
                    )
                    continue
                target = found
            if window_size(max(candidate.window_minutes, definition.min_interval_minutes or 0)) is None:
                skipped.append(
                    {
                        "resource_name": resource.name,
                        "rule": f"{candidate.rule_label}: {definition.label}",
                        "reason": "Azure metric alerts support windows of up to 24 hours.",
                    }
                )
                continue
            sub = subscriptions.get(target.subscription_ref_id)
            sub_id = target.subscription_id.lower()
            template = templates.setdefault(
                sub_id, _Template(sub_id, (sub.display_name if sub and sub.display_name else sub_id))
            )
            name = _alert_name(template, candidate, target)
            template.names.add(name)
            template.alerts.append(_metric_alert(name, candidate, definition, target))
            covered.add(resource.id)

    out = []
    for sub_id in sorted(templates, key=lambda s: (templates[s].subscription_name.lower(), s)):
        template = templates[sub_id]
        out.append(
            {
                "subscription_id": sub_id,
                "subscription_name": template.subscription_name,
                "filename": f"azure-alerts-{_slug(template.subscription_name, 50)}-{sub_id[:8]}",
                "alert_count": len(template.alerts),
                "template": _arm_template(template, group_name, recipients or []),
            }
        )
    return {"templates": out, "skipped": skipped, "resources": len(covered)}
