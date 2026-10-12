"""Alert templates: catalogue, customisation, assignments, the alert plan, tiered evaluation and export."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.db.session import session_scope
from app.services.alerts.evaluator import evaluate_alert_rules
from app.services.alerts.templates import tier_order_error
from app.services.azure.provider import get_azure_services
from app.services.monitors.registry import all_monitors
from tests.conftest import OTHER_TENANT, auth_headers
from tests.helpers import find_resource, seeded

ADMIN = auth_headers("admin")
VIEWER = auth_headers("viewer")
TEMPLATES = "/api/v1/alert-templates"
ASSIGNMENTS = "/api/v1/alert-template-assignments"
SECRET = "org-0-teams-alerts"
WEBHOOK = "https://example.test/workflows/teams"


# ---------------------------------------------------------------- helpers


@pytest.fixture
def posts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every Teams card that would have been posted (nothing leaves the test)."""
    sent: list[dict[str, Any]] = []

    async def fake_post(url: str, body: dict[str, Any]) -> None:
        sent.append(body["attachments"][0]["content"])

    monkeypatch.setenv("SECRET_ORG_0_TEAMS_ALERTS", WEBHOOK)
    monkeypatch.setattr("app.services.alerts.channels.registry._post", fake_post)
    return sent


def _summaries(posts: list[dict[str, Any]]) -> list[str]:
    return [str(card["body"][0]["text"]) for card in posts]


@pytest.fixture
def metric_values(monkeypatch: pytest.MonkeyPatch) -> dict[str, float | None]:
    """Template metric values by metric key, instead of Azure (missing key = unreadable)."""
    values: dict[str, float | None] = {}

    async def fake_values(db: Any, azure: Any, tenants: Any, work: list[Any]) -> list[float | None]:
        return [values.get(rule.metric) for _, rule, _ in work]

    monkeypatch.setattr("app.services.alerts.evaluator._template_values", fake_values)
    return values


async def _org_id(client: httpx.AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get("/api/v1/auth/me", headers=ADMIN)).json()["organization_id"])


async def _evaluate(org: uuid.UUID, force: bool = True) -> dict[str, int]:
    async with session_scope() as db:
        return await evaluate_alert_rules(db, get_azure_services(), org, force=force)


async def _assign(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    r = await client.post(ASSIGNMENTS, json=body, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


async def _teams(client: httpx.AsyncClient, min_severity: str = "warning") -> dict[str, Any]:
    r = await client.post(
        "/api/v1/notifications/teams-channels",
        json={"name": "Ops", "secret_ref": SECRET, "min_severity": min_severity},
        headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _open_template_alerts(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    items = (await client.get("/api/v1/alerts", params={"status": "open", "page_size": 200}, headers=ADMIN)).json()
    return [a for a in items["items"] if a["source"] == "template"]


# ---------------------------------------------------------------- catalogue


def test_every_template_rule_has_ordered_tiers() -> None:
    rules = [(m.key, r) for m in all_monitors() for r in m.health_rules]
    assert len(rules) > 40
    for key, rule in rules:
        assert tier_order_error(rule.operator, rule.info, rule.warning, rule.critical) is None, (key, rule.metric)
        assert rule.frequency_minutes >= 1
    with_info = [r for _, r in rules if r.info is not None]
    # Only binary signals (DDoS, unhealthy hosts, VM availability) have no informational tier.
    assert len(rules) - len(with_info) <= 3


def test_tier_ordering_messages() -> None:
    assert tier_order_error("gt", 70, 80, 90) is None
    assert tier_order_error("lt", 99, 95, 80) is None
    assert "Info < Warning < Critical" in str(tier_order_error("gt", 90, 80, 95))
    assert "Info > Warning > Critical" in str(tier_order_error("lt", 90, 95, 80))


async def test_templates_are_listed_with_recommended_tiers(client: httpx.AsyncClient) -> None:
    await seeded(client)
    templates = {t["monitor_key"]: t for t in (await client.get(TEMPLATES, headers=VIEWER)).json()}
    assert "generic" not in templates and "sql_server" not in templates  # no health rules, no template
    app = templates["app_service"]
    assert app["resource_count"] > 0 and app["covered_count"] == 0 and app["customized"] is False
    cpu = next(r for r in app["rules"] if r["metric"] == "plan_cpu")
    assert (cpu["info"], cpu["warning"], cpu["critical"]) == (70, 80, 90)
    assert cpu["operator"] == "gt" and cpu["frequency_minutes"] == 5 and cpu["unit"] == "percent"
    assert (await client.get(f"{TEMPLATES}/app_service", headers=VIEWER)).json()["rules"] == app["rules"]
    assert (await client.get(f"{TEMPLATES}/generic", headers=VIEWER)).status_code == 404


async def test_customising_a_rule_drives_health_and_can_be_reset(client: httpx.AsyncClient) -> None:
    await seeded(client)
    url = f"{TEMPLATES}/app_service_plan/rules/cpu"
    bad = await client.put(url, json={"enabled": True, "info": 90, "warning": 80, "critical": 95}, headers=ADMIN)
    assert bad.status_code == 422 and "Info < Warning < Critical" in bad.json()["error"]["message"]
    empty = await client.put(
        url, json={"enabled": True, "info": None, "warning": None, "critical": None}, headers=ADMIN
    )
    assert empty.status_code == 422
    body = {"enabled": True, "info": None, "warning": 0, "critical": 1, "window_minutes": 30}
    assert (await client.put(url, json=body, headers=VIEWER)).status_code == 403
    saved = await client.put(url, json=body, headers=ADMIN)
    assert saved.status_code == 200, saved.text
    rule = saved.json()
    assert (rule["info"], rule["warning"], rule["critical"], rule["window_minutes"]) == (None, 0, 1, 30)
    assert rule["customized"] is True and rule["default_warning"] == 80

    # Health status follows the customised warning/critical thresholds.
    plan = await find_resource(client, "asp-crm-prod-uks")
    evaluated = await client.post(f"/api/v1/resources/{plan['id']}/health/evaluate", headers=auth_headers("operator"))
    assert evaluated.json()["health_status"] == "critical"
    assert (await client.get(f"{TEMPLATES}/app_service_plan", headers=VIEWER)).json()["customized"] is True

    reset = await client.delete(url, headers=ADMIN)
    assert reset.status_code == 200
    assert (reset.json()["info"], reset.json()["warning"], reset.json()["customized"]) == (70, 80, False)


async def test_legacy_health_rule_endpoint_still_customises_templates(client: httpx.AsyncClient) -> None:
    r = await client.put(
        "/api/v1/health-rules",
        json={"monitor_key": "redis", "metric_name": "memory", "warning_threshold": 85, "critical_threshold": 97},
        headers=auth_headers("super_admin"),
    )
    assert r.status_code == 200, r.text
    rule = next(
        x for x in (await client.get(f"{TEMPLATES}/redis", headers=VIEWER)).json()["rules"] if x["metric"] == "memory"
    )
    # The recommended info tier (70) still sits below the new warning, so it is kept.
    assert (rule["info"], rule["warning"], rule["critical"], rule["customized"]) == (70, 85, 97, True)


# ---------------------------------------------------------------- assignments


async def test_assignment_scopes_conflicts_and_precedence(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    crm = data["crm"]
    prod = next(e for e in crm["environments"] if e["slug"] == "prod")
    app = await find_resource(client, "app-crm-prod-uks")
    vnet = await find_resource(client, "vnet-crm-prod-uks")

    org = await _assign(client)
    project = await _assign(client, project_id=crm["id"])
    env = await _assign(client, project_id=crm["id"], environment_id=prod["id"])
    single = await _assign(
        client, resource_id=app["id"], overrides={"app_service:plan_cpu": {"warning": 60, "critical": 75, "info": 50}}
    )
    assert [a["scope"] for a in (org, project, env, single)] == ["organization", "project", "environment", "resource"]
    assert single["resource_name"] == "app-crm-prod-uks" and env["environment_name"] == "Production"

    duplicate = await client.post(ASSIGNMENTS, json={"project_id": crm["id"]}, headers=ADMIN)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ASSIGNMENT_EXISTS"
    assert duplicate.json()["error"]["details"]["id"] == project["id"]

    no_template = await client.post(ASSIGNMENTS, json={"resource_id": vnet["id"]}, headers=ADMIN)
    assert no_template.status_code == 422
    orphan_env = await client.post(ASSIGNMENTS, json={"environment_id": prod["id"]}, headers=ADMIN)
    assert orphan_env.status_code == 422
    wrong_env = await client.post(
        ASSIGNMENTS, json={"project_id": data["prism"]["id"], "environment_id": prod["id"]}, headers=ADMIN
    )
    assert wrong_env.status_code == 422
    unknown = await client.post(ASSIGNMENTS, json={"overrides": {"app_service:nope": {"warning": 1}}}, headers=ADMIN)
    assert unknown.status_code == 422
    disordered = await client.patch(
        f"{ASSIGNMENTS}/{org['id']}", json={"overrides": {"app_service:plan_cpu": {"info": 95}}}, headers=ADMIN
    )
    assert disordered.status_code == 422
    assert (await client.post(ASSIGNMENTS, json={}, headers=VIEWER)).status_code == 403

    # Coverage: each resource counts once, for its most specific assignment.
    listed = {a["id"]: a for a in (await client.get(ASSIGNMENTS, headers=VIEWER)).json()}
    assert listed[single["id"]]["covered_resources"] == 1 and listed[single["id"]]["templates"] == ["app_service"]
    assert listed[env["id"]]["covered_resources"] >= 1
    total = sum(a["covered_resources"] for a in listed.values())
    templates = {t["monitor_key"]: t for t in (await client.get(TEMPLATES, headers=VIEWER)).json()}
    assert (
        total
        == sum(t["covered_count"] for t in templates.values())
        == sum(t["resource_count"] for t in templates.values())
    )
    filtered = (await client.get(ASSIGNMENTS, params={"project_id": crm["id"]}, headers=VIEWER)).json()
    assert {a["scope"] for a in filtered} == {"project", "environment"}

    # The alert plan shows the most specific assignment and its effective, overridden values.
    plan = (await client.get(f"/api/v1/resources/{app['id']}/alert-plan", headers=VIEWER)).json()
    assert plan["assignment"]["id"] == single["id"] and plan["template"]["monitor_key"] == "app_service"
    cpu = next(r for r in plan["rules"] if r["metric"] == "plan_cpu")
    assert (cpu["info"], cpu["warning"], cpu["critical"], cpu["overridden"]) == (50, 60, 75, True)
    assert cpu["current_tier"] in ("ok", "info", "warning", "critical", "unknown")
    other = next(r for r in plan["rules"] if r["metric"] == "http5xx")
    assert other["overridden"] is False

    # Removing the resource assignment falls back to the environment's.
    assert (await client.delete(f"{ASSIGNMENTS}/{single['id']}", headers=ADMIN)).status_code == 204
    plan = (await client.get(f"/api/v1/resources/{app['id']}/alert-plan", headers=VIEWER)).json()
    assert plan["assignment"]["id"] == env["id"]


async def test_assignment_channels_must_be_org_channels(client: httpx.AsyncClient) -> None:
    lst = await client.post(
        "/api/v1/notifications/email-lists", json={"name": "x", "recipients": ["a@contoso.com"]}, headers=ADMIN
    )
    bad = await client.post(ASSIGNMENTS, json={"notification_channel_ids": [lst.json()["id"]]}, headers=ADMIN)
    assert bad.status_code == 422
    missing = await client.post(ASSIGNMENTS, json={"notification_channel_ids": [str(uuid.uuid4())]}, headers=ADMIN)
    assert missing.status_code == 422


async def test_alert_plan_for_inventory_and_other_organisations(client: httpx.AsyncClient) -> None:
    await seeded(client)
    vnet = await find_resource(client, "vnet-crm-prod-uks")
    plan = (await client.get(f"/api/v1/resources/{vnet['id']}/alert-plan", headers=VIEWER)).json()
    assert plan["template"] is None and plan["rules"] == []
    app = await find_resource(client, "app-crm-prod-uks")
    other = auth_headers("viewer", tenant=OTHER_TENANT)
    assert (await client.get(f"/api/v1/resources/{app['id']}/alert-plan", headers=other)).status_code == 404
    created = await _assign(client)
    assert (await client.get(ASSIGNMENTS, headers=other)).json() == []
    other_admin = auth_headers("admin", tenant=OTHER_TENANT)
    assert (
        await client.patch(f"{ASSIGNMENTS}/{created['id']}", json={"enabled": False}, headers=other_admin)
    ).status_code == 404


# ---------------------------------------------------------------- evaluation


async def test_tiers_escalate_ease_and_resolve_with_the_right_notifications(
    client: httpx.AsyncClient, posts: list[dict[str, Any]], metric_values: dict[str, float | None]
) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _teams(client, min_severity="warning")
    app = await find_resource(client, "app-crm-prod-uks")
    await _assign(client, resource_id=app["id"])

    def cpu_alert(alerts: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next(
            (a for a in alerts if a["resource_name"] == "app-crm-prod-uks" and a["metric_name"] == "Plan CPU"), None
        )

    # Info: an alert is open, nobody is notified.
    metric_values["plan_cpu"] = 72
    stats = await _evaluate(org)
    assert stats["template_fired"] == 1 and stats["fired"] == 0
    alert = cpu_alert(await _open_template_alerts(client))
    assert alert and alert["severity"] == "info" and alert["title"] == "Plan CPU above 70% on app-crm-prod-uks"
    assert posts == []

    # Warning, then critical: each escalation is announced.
    metric_values["plan_cpu"] = 85
    assert (await _evaluate(org))["template_escalated"] == 1
    metric_values["plan_cpu"] = 95
    assert (await _evaluate(org))["template_escalated"] == 1
    alert = cpu_alert(await _open_template_alerts(client))
    assert alert and alert["severity"] == "critical" and alert["threshold"] == 90
    assert [s.split("]")[0] for s in _summaries(posts)] == ["[WARNING", "[CRITICAL"]
    assert "Plan CPU above 90% on app-crm-prod-uks" in _summaries(posts)[-1]

    # Easing back to warning is recorded but not announced; the same alert stays open.
    metric_values["plan_cpu"] = 82
    assert (await _evaluate(org))["template_deescalated"] == 1
    assert len(posts) == 2
    eased = cpu_alert(await _open_template_alerts(client))
    assert eased and eased["id"] == alert["id"] and eased["severity"] == "warning"
    detail = (await client.get(f"/api/v1/alerts/{alert['id']}", headers=ADMIN)).json()
    assert sorted(e["event_type"] for e in detail["events"] if e["event_type"] in ("escalated", "de-escalated")) == [
        "de-escalated",
        "escalated",
        "escalated",
    ]

    # Unreadable: nothing changes.
    metric_values.pop("plan_cpu")
    assert (await _evaluate(org))["template_no_data"] >= 1
    assert cpu_alert(await _open_template_alerts(client))

    # Below info: resolved, and the recovery is announced because it had been a warning.
    metric_values["plan_cpu"] = 40
    assert (await _evaluate(org))["template_resolved"] == 1
    assert cpu_alert(await _open_template_alerts(client)) is None
    assert _summaries(posts)[-1].startswith("[RESOLVED]")


async def test_info_only_alerts_resolve_silently(
    client: httpx.AsyncClient, posts: list[dict[str, Any]], metric_values: dict[str, float | None]
) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _teams(client, min_severity="warning")
    await _assign(client)
    metric_values["plan_cpu"] = 72
    await _evaluate(org)
    metric_values["plan_cpu"] = 10
    await _evaluate(org)
    assert posts == []


async def test_assignment_channels_are_notified_once(
    client: httpx.AsyncClient, posts: list[dict[str, Any]], metric_values: dict[str, float | None]
) -> None:
    await seeded(client)
    org = await _org_id(client)
    channel = await client.post(
        "/api/v1/notification-channels",
        json={"name": "Rule-only Teams", "channel_type": "teams", "secret_ref": SECRET},
        headers=ADMIN,
    )
    app = await find_resource(client, "app-crm-prod-uks")
    await _assign(client, resource_id=app["id"], notification_channel_ids=[channel.json()["id"]])
    metric_values["plan_cpu"] = 95
    await _evaluate(org)
    cpu_posts = [s for s in _summaries(posts) if "Plan CPU" in s]
    assert len(cpu_posts) == 1 and cpu_posts[0].startswith("[CRITICAL]")


async def test_frequency_skips_until_due_unless_forced(
    client: httpx.AsyncClient, metric_values: dict[str, float | None]
) -> None:
    await seeded(client)
    org = await _org_id(client)
    app = await find_resource(client, "app-crm-prod-uks")
    await _assign(client, resource_id=app["id"])
    metric_values["plan_cpu"] = 72
    first = await _evaluate(org, force=False)
    assert first["template_skipped"] == 0 and first["template_fired"] == 1
    second = await _evaluate(org, force=False)
    assert second["template_skipped"] == second["template_rules"] > 0
    forced = await _evaluate(org, force=True)
    assert forced["template_skipped"] == 0


async def test_losing_coverage_resolves_template_alerts(
    client: httpx.AsyncClient, metric_values: dict[str, float | None]
) -> None:
    await seeded(client)
    org = await _org_id(client)
    app = await find_resource(client, "app-crm-prod-uks")
    assignment = await _assign(client, resource_id=app["id"])
    metric_values.update({"plan_cpu": 95, "http5xx": 60})
    await _evaluate(org)
    assert len(await _open_template_alerts(client)) == 2

    # Disabling one rule closes its alert on the next run.
    await client.patch(
        f"{ASSIGNMENTS}/{assignment['id']}",
        json={"overrides": {"app_service:http5xx": {"enabled": False}}},
        headers=ADMIN,
    )
    stats = await _evaluate(org)
    assert stats["template_closed"] == 1
    assert [a["metric_name"] for a in await _open_template_alerts(client)] == ["Plan CPU"]

    # Disabling the assignment closes the rest straight away.
    await client.patch(f"{ASSIGNMENTS}/{assignment['id']}", json={"enabled": False}, headers=ADMIN)
    assert await _open_template_alerts(client) == []


async def test_real_metrics_and_evaluate_now(client: httpx.AsyncClient, posts: list[dict[str, Any]]) -> None:
    """End to end with the mock estate: PRISM production runs hot (CPU about 80-88%)."""
    from app.services.jobs import wait_for_inline_jobs

    data = await seeded(client)
    await _teams(client, min_severity="warning")
    await _assign(client, project_id=data["prism"]["id"])
    started = await client.post("/api/v1/alert-rules/evaluate", headers=ADMIN)
    assert started.status_code == 202, started.text
    await wait_for_inline_jobs()
    hot = [a for a in await _open_template_alerts(client) if a["resource_name"] == "asp-prism-prod-uks"]
    assert hot and {a["severity"] for a in hot} <= {"info", "warning", "critical"}
    assert any(a["metric_name"] == "CPU" and a["severity"] in ("warning", "critical") for a in hot)
    assert any("asp-prism-prod-uks" in s for s in _summaries(posts))
    # Nothing outside the assigned project is evaluated.
    assert all(a["resource_name"].find("prism") >= 0 for a in await _open_template_alerts(client))


# ---------------------------------------------------------------- export


async def test_export_includes_info_tier_and_assignment_overrides(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    await _assign(
        client, resource_id=app["id"], overrides={"app_service:plan_cpu": {"info": 50, "warning": 60, "critical": 75}}
    )

    body = (await client.get("/api/v1/alert-rules/azure-export", params={"covered_only": True}, headers=ADMIN)).json()
    alerts = [
        r
        for t in body["templates"]
        for r in t["template"]["resources"]
        if r["type"] == "Microsoft.Insights/metricAlerts"
    ]
    names = {a["name"]: a for a in alerts}
    assert body["resources"] == 1
    info = names["amp-app-crm-prod-uks-plan_cpu-info"]
    assert info["properties"]["severity"] == 3
    assert info["properties"]["criteria"]["allOf"][0]["threshold"] == 50
    assert names["amp-app-crm-prod-uks-plan_cpu-warning"]["properties"]["criteria"]["allOf"][0]["threshold"] == 60
    assert "assignment override" in info["properties"]["description"]

    everything = (await client.get("/api/v1/alert-rules/azure-export", headers=ADMIN)).json()
    assert everything["resources"] > 1
