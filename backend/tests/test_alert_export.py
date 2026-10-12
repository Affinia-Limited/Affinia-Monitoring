"""Alerting rules exported as deployable Azure Monitor ARM templates."""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest

from app.core.errors import ValidationFailedError
from app.services.alerts.azure_export import (
    action_group_name,
    evaluation_frequency,
    parse_recipients,
    short_name,
    window_size,
)
from tests.conftest import OTHER_TENANT, auth_headers
from tests.helpers import SUB_A, SUB_B, connect, create_project, find_resource, seeded

URL = "/api/v1/alert-rules/azure-export"
ADMIN = auth_headers("admin")
_BAD_NAME = re.compile(r"[*<>%&:\\?+/#\x00-\x1f\x7f]")


async def _export(client: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(URL, params=params, headers=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()


def _alerts(template: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in template["resources"] if r["type"] == "Microsoft.Insights/metricAlerts"]


def _all_alerts(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for t in body["templates"] for a in _alerts(t["template"])]


def _find(body: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [a for a in _all_alerts(body) if a["name"] == name]
    assert matches, f"{name} not in {[a['name'] for a in _all_alerts(body)][:20]}"
    return matches[0]


def _criterion(alert: dict[str, Any]) -> dict[str, Any]:
    return alert["properties"]["criteria"]["allOf"][0]


async def test_template_is_valid_arm(client: httpx.AsyncClient) -> None:
    await seeded(client)
    body = await _export(client, recipients="Ops@Contoso.com, ops@contoso.com;\noncall@contoso.com")

    assert body["resources"] > 0 and len(body["templates"]) == 1
    entry = body["templates"][0]
    assert entry["subscription_id"] == SUB_A
    assert entry["filename"].startswith("azure-alerts-") and "/" not in entry["filename"]
    template = entry["template"]
    assert template["$schema"].endswith("2019-04-01/deploymentTemplate.json#")
    assert template["contentVersion"] == "1.0.0.0"
    params = template["parameters"]
    # Lower-cased and de-duplicated.
    assert params["emailReceivers"]["defaultValue"] == ["ops@contoso.com", "oncall@contoso.com"]
    assert params["actionGroupName"]["defaultValue"] == "amp-alerts"
    assert len(params["actionGroupShortName"]["defaultValue"]) <= 12
    assert params["alertsEnabled"] == {**params["alertsEnabled"], "type": "bool", "defaultValue": True}

    group = template["resources"][0]
    assert group["type"] == "Microsoft.Insights/actionGroups" and group["apiVersion"] == "2023-01-01"
    assert group["location"] == "Global" and group["name"] == "[parameters('actionGroupName')]"
    [loop] = group["properties"]["copy"]
    assert loop["name"] == "emailReceivers" and loop["count"] == "[length(parameters('emailReceivers'))]"
    assert loop["input"]["emailAddress"] == "[parameters('emailReceivers')[copyIndex('emailReceivers')]]"

    alerts = _alerts(template)
    assert len(alerts) == entry["alert_count"] == template["outputs"]["alertRuleCount"]["value"]
    names = [a["name"] for a in alerts]
    assert len(set(names)) == len(names)
    group_id = "[resourceId('Microsoft.Insights/actionGroups', parameters('actionGroupName'))]"
    for alert in alerts:
        assert alert["apiVersion"] == "2018-03-01" and alert["location"] == "global"
        assert len(alert["name"]) <= 260 and not _BAD_NAME.search(alert["name"])
        assert alert["dependsOn"] == [group_id]
        props = alert["properties"]
        assert props["actions"] == [{"actionGroupId": group_id}]
        assert props["enabled"] == "[parameters('alertsEnabled')]" and props["autoMitigate"] is True
        assert props["severity"] in (0, 1, 2, 3, 4)
        assert props["scopes"][0].startswith(f"/subscriptions/{SUB_A}/")
        assert props["criteria"]["odata.type"] == "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria"
        criterion = _criterion(alert)
        assert criterion["criterionType"] == "StaticThresholdCriterion"
        assert criterion["operator"] in ("GreaterThan", "GreaterThanOrEqual", "LessThan", "LessThanOrEqual")
        assert criterion["timeAggregation"] in ("Average", "Total", "Maximum", "Minimum", "Count")
        window = props["windowSize"]
        assert window in ("PT1M", "PT5M", "PT15M", "PT30M", "PT1H", "PT6H", "PT12H", "PT24H")
        assert props["evaluationFrequency"] in ("PT1M", "PT5M", "PT15M", "PT30M", "PT1H")


async def test_thresholds_are_converted_to_azure_units(client: httpx.AsyncClient) -> None:
    await seeded(client)
    body = await _export(client)

    # Response time is shown in milliseconds but Azure reports HttpResponseTime in seconds.
    warning = _find(body, "amp-app-crm-prod-uks-response_time-warning")
    assert _criterion(warning)["metricName"] == "HttpResponseTime"
    assert _criterion(warning)["metricNamespace"] == "microsoft.web/sites"
    assert _criterion(warning)["threshold"] == 1.0
    assert _criterion(warning)["timeAggregation"] == "Average"
    assert warning["properties"]["severity"] == 2
    critical = _find(body, "amp-app-crm-prod-uks-response_time-critical")
    assert _criterion(critical)["threshold"] == 3.0 and critical["properties"]["severity"] == 0

    # HTTP 5xx is a count summed over 15 minutes: a Total over a 15-minute window.
    errors = _find(body, "amp-app-crm-prod-uks-http5xx-warning")
    assert _criterion(errors)["timeAggregation"] == "Total" and _criterion(errors)["threshold"] == 10
    assert errors["properties"]["windowSize"] == "PT15M" and errors["properties"]["evaluationFrequency"] == "PT5M"
    # "Below" thresholds keep their direction.
    assert _criterion(_find(body, "amp-app-crm-prod-uks-health_check-critical"))["operator"] == "LessThan"


async def test_metrics_on_related_resources_target_that_resource(client: httpx.AsyncClient) -> None:
    await seeded(client)
    plan = await find_resource(client, "asp-crm-prod-uks")
    body = await _export(client)

    alert = _find(body, "amp-app-crm-prod-uks-plan_cpu-warning")
    assert alert["properties"]["scopes"] == [plan["azure_id"]]
    assert alert["properties"]["targetResourceType"] == "microsoft.web/serverfarms"
    assert alert["properties"]["targetResourceRegion"] == plan["location"]
    assert _criterion(alert)["metricName"] == "CpuPercentage"
    assert "measured on asp-crm-prod-uks" in alert["properties"]["description"]


async def test_overrides_and_disabled_rules_are_respected(client: httpx.AsyncClient) -> None:
    await seeded(client)
    for override in (
        {"monitor_key": "app_service_plan", "metric_name": "cpu", "warning_threshold": 70, "critical_threshold": None},
        {"monitor_key": "app_service_plan", "metric_name": "memory", "enabled": False},
    ):
        response = await client.put("/api/v1/health-rules", json=override, headers=auth_headers("super_admin"))
        assert response.status_code == 200, response.text
    body = await _export(client)

    cpu = _find(body, "amp-asp-crm-prod-uks-cpu-warning")
    assert _criterion(cpu)["threshold"] == 70
    assert "organisation override" in cpu["properties"]["description"]
    names = {a["name"] for a in _all_alerts(body)}
    # The override removed the critical threshold, and the disabled rule exports nothing.
    assert "amp-asp-crm-prod-uks-cpu-critical" not in names
    assert not any(n.startswith("amp-asp-crm-prod-uks-memory-") for n in names)


async def test_custom_alert_rules_are_exported(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    rule = {
        "name": "Slow checkout",
        "monitor_key": "app_service",
        "metric_name": "response_time",
        "aggregation": "Maximum",
        "operator": "gte",
        "threshold": 2000,
        "severity": "critical",
        "window_minutes": 10,
        "resource_id": app["id"],
    }
    created = await client.post("/api/v1/alert-rules", json=rule, headers=ADMIN)
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    body = await _export(client)
    alert = _find(body, f"amp-app-crm-prod-uks-response_time-slow-checkout-{rule_id[:8]}")
    criterion = _criterion(alert)
    assert (criterion["operator"], criterion["threshold"], criterion["timeAggregation"]) == (
        "GreaterThanOrEqual",
        2.0,
        "Maximum",
    )
    assert alert["properties"]["severity"] == 0
    # 10 minutes rounds up to Azure's 15-minute window.
    assert alert["properties"]["windowSize"] == "PT15M"
    assert "Slow checkout" in alert["properties"]["description"]
    # Only the resource in the rule's scope gets it.
    assert sum("slow-checkout" in a["name"] for a in _all_alerts(body)) == 1

    without_rules = await _export(client, include_rules=False)
    assert not any("slow-checkout" in a["name"] for a in _all_alerts(without_rules))
    only_rules = await _export(client, include_health=False)
    assert [a["name"] for a in _all_alerts(only_rules)] == [alert["name"]]


async def test_scope_filters_resources(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    crm = data["crm"]
    prod = next(e for e in crm["environments"] if e["slug"] == "prod")
    body = await _export(client, project_id=crm["id"], environment_id=prod["id"])

    listed = await client.get(
        "/api/v1/resources",
        params={"project_id": crm["id"], "environment_id": prod["id"], "monitored_only": True, "page_size": 200},
        headers=ADMIN,
    )
    names = {r["name"] for r in listed.json()["items"]}
    alerts = _all_alerts(body)
    assert alerts
    assert all(any(a["name"].startswith(f"amp-{n}-") for n in names) for a in alerts)
    assert body["resources"] <= len(names)

    app = await find_resource(client, "app-crm-prod-uks")
    single = await _export(client, resource_id=app["id"])
    assert single["resources"] == 1
    assert all(a["name"].startswith("amp-app-crm-prod-uks-") for a in _all_alerts(single))

    # An environment from another project is refused.
    prism_prod = next(e for e in data["prism"]["environments"] if e["slug"] == "prod")
    mixed = await client.get(URL, params={"project_id": crm["id"], "environment_id": prism_prod["id"]}, headers=ADMIN)
    assert mixed.status_code == 422


async def test_one_template_per_subscription(client: httpx.AsyncClient) -> None:
    for slug in ("crm", "prism", "datacore"):
        await create_project(client, slug)
    await connect(client, [SUB_A, SUB_B])
    body = await _export(client)

    subs = [t["subscription_id"] for t in body["templates"]]
    assert sorted(subs) == sorted([SUB_A, SUB_B])
    for entry in body["templates"]:
        for alert in _alerts(entry["template"]):
            assert alert["properties"]["scopes"][0].startswith(f"/subscriptions/{entry['subscription_id']}/")
    assert len({t["filename"] for t in body["templates"]}) == 2


async def test_export_is_deterministic(client: httpx.AsyncClient) -> None:
    await seeded(client)
    first = await _export(client)
    second = await _export(client)
    strip = [{**t, "template": {**t["template"], "metadata": None}} for t in first["templates"]]
    assert strip == [{**t, "template": {**t["template"], "metadata": None}} for t in second["templates"]]


async def test_permissions_and_isolation(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    for role in ("viewer", "operator"):
        assert (await client.get(URL, headers=auth_headers(role))).status_code == 403
    assert (await client.get(URL)).status_code == 401

    other = auth_headers("admin", tenant=OTHER_TENANT)
    # Another organisation sees nothing of this one, and cannot name its projects.
    assert (await client.get(URL, headers=other)).json()["templates"] == []
    refused = await client.get(URL, params={"project_id": data["crm"]["id"]}, headers=other)
    assert refused.status_code == 404


async def test_recipients_are_validated_and_never_audited(client: httpx.AsyncClient) -> None:
    await seeded(client)
    bad = await client.get(URL, params={"recipients": "ops@contoso.com, not-an-address"}, headers=ADMIN)
    assert bad.status_code == 422
    assert "not-an-address" not in bad.text
    many = ",".join(f"user{i}@contoso.com" for i in range(51))
    assert (await client.get(URL, params={"recipients": many}, headers=ADMIN)).status_code == 422

    await _export(client, recipients="ops@contoso.com", action_group_name="Prod / On-call #1")
    logs = await client.get("/api/v1/audit-logs", params={"action": "alerts.azure_exported"}, headers=ADMIN)
    [entry] = logs.json()["items"]
    assert entry["details"]["recipients"] == 1 and entry["details"]["alert_rules"] > 0
    assert "@" not in str(entry["details"])


async def test_action_group_name_is_sanitised(client: httpx.AsyncClient) -> None:
    await seeded(client)
    body = await _export(client, action_group_name="Prod / On-call #1")
    params = body["templates"][0]["template"]["parameters"]
    assert params["actionGroupName"]["defaultValue"] == "Prod - On-call -1"
    assert params["actionGroupShortName"]["defaultValue"] == "Prod-On-call"


def test_helpers() -> None:
    assert [window_size(m) for m in (1, 2, 5, 15, 16, 60, 61, 1440)] == [
        "PT1M",
        "PT5M",
        "PT5M",
        "PT15M",
        "PT30M",
        "PT1H",
        "PT6H",
        "PT24H",
    ]
    assert window_size(1441) is None
    assert [evaluation_frequency(w) for w in ("PT1M", "PT5M", "PT15M", "PT1H", "PT6H", "PT24H")] == [
        "PT1M",
        "PT1M",
        "PT5M",
        "PT15M",
        "PT15M",
        "PT1H",
    ]
    assert action_group_name("  ") == "amp-alerts"
    assert short_name("!!!") == "amp-alerts"
    assert parse_recipients(None) == []
    with pytest.raises(ValidationFailedError):
        parse_recipients("a@b")
