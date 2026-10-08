"""Health evaluation from real signals, alert rules, and notifications."""

from __future__ import annotations

import httpx
import pytest

from app.services.health.evaluator import classify
from app.services.monitors.base import HealthRule
from tests.conftest import auth_headers
from tests.helpers import find_resource, seeded


@pytest.mark.parametrize(
    ("value", "operator", "expected"),
    [
        (95, "gt", "critical"),
        (85, "gt", "warning"),
        (50, "gt", "healthy"),
        (70, "lt", "critical"),
        (90, "lt", "warning"),
        (99, "lt", "healthy"),
    ],
)
def test_classify(value: float, operator: str, expected: str) -> None:
    rule = HealthRule("m", operator, 80 if operator == "gt" else 95, 90 if operator == "gt" else 80)  # type: ignore[arg-type]
    assert classify(value, rule, rule.warning, rule.critical) == expected


async def test_health_uses_resource_health_and_metrics(client: httpx.AsyncClient) -> None:
    await seeded(client)
    degraded = await find_resource(client, "app-prism-prod-uks")
    assert degraded["health_status"] in ("warning", "critical")
    signals = {r["signal"] for r in degraded["health_reasons"]}
    assert "resource_health" in signals
    # PRISM production is under CPU pressure in the demo estate.
    assert any(r.get("metric") == "plan_cpu" for r in degraded["health_reasons"])

    healthy = await find_resource(client, "app-crm-dev-uks")
    assert healthy["health_status"] == "healthy"
    assert healthy["health_reasons"] == []


async def test_threshold_override_changes_health(client: httpx.AsyncClient) -> None:
    await seeded(client)
    plan = await find_resource(client, "asp-crm-dev-uks")
    viewer = await client.post(f"/api/v1/resources/{plan['id']}/health/evaluate", headers=auth_headers("viewer"))
    assert viewer.status_code == 403
    r = await client.put(
        "/api/v1/health-rules",
        json={"monitor_key": "app_service_plan", "metric_name": "cpu", "warning_threshold": 0, "critical_threshold": 1},
        headers=auth_headers("super_admin"),
    )
    assert r.status_code == 200 and r.json()["overridden"] is True
    evaluated = (
        await client.post(f"/api/v1/resources/{plan['id']}/health/evaluate", headers=auth_headers("operator"))
    ).json()
    assert evaluated["health_status"] == "critical"
    assert (
        await client.put(
            "/api/v1/health-rules",
            json={"monitor_key": "app_service_plan", "metric_name": "nope"},
            headers=auth_headers("super_admin"),
        )
    ).status_code == 422
    assert (
        await client.put(
            "/api/v1/health-rules",
            json={"monitor_key": "app_service_plan", "metric_name": "cpu"},
            headers=auth_headers("admin"),
        )
    ).status_code == 403


async def test_unknown_when_no_signals(client: httpx.AsyncClient) -> None:
    await seeded(client)
    vnet = await find_resource(client, "vnet-crm-prod-uks")
    # Generic resources only have Resource Health; the mock reports Available.
    assert vnet["health_status"] == "healthy"

    from app.services.azure.mock.services import MockLogsService, MockMetricsService, MockResourceGraphService
    from app.services.azure.provider import set_azure_services
    from app.services.azure.types import AzureServices

    class NoHealth(MockResourceGraphService):
        async def resource_health(self, tenant_id, subscription_ids):  # type: ignore[no-untyped-def]
            return []

    set_azure_services(AzureServices(NoHealth(), MockMetricsService(), MockLogsService(), is_mock=True))
    from app.core.cache import MemoryCache, set_cache

    set_cache(MemoryCache())
    evaluated = (
        await client.post(f"/api/v1/resources/{vnet['id']}/health/evaluate", headers=auth_headers("operator"))
    ).json()
    assert evaluated["health_status"] == "unknown"


async def _rule(client: httpx.AsyncClient, **overrides: object) -> dict:
    body = {
        "name": "High plan CPU",
        "monitor_key": "app_service",
        "metric_name": "plan_cpu",
        "aggregation": "Average",
        "operator": "gt",
        "threshold": 50,
        "severity": "critical",
        "window_minutes": 15,
        **overrides,
    }
    r = await client.post("/api/v1/alert-rules", json=body, headers=auth_headers("admin"))
    assert r.status_code == 201, r.text
    return r.json()


async def test_alert_rule_fires_acknowledges_and_resolves(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    prod = next(e for e in data["prism"]["environments"] if e["slug"] == "prod")
    rule = await _rule(client, project_id=data["prism"]["id"], environment_id=prod["id"], threshold=70)

    from app.db.session import session_scope
    from app.services.alerts.evaluator import evaluate_alert_rules
    from app.services.azure.provider import get_azure_services

    me = (await client.get("/api/v1/auth/me", headers=auth_headers("admin"))).json()
    import uuid

    async with session_scope() as db:
        stats = await evaluate_alert_rules(db, get_azure_services(), uuid.UUID(me["organization_id"]))
    assert stats["fired"] == 1

    alerts = (await client.get("/api/v1/alerts", params={"status": "active"}, headers=auth_headers("viewer"))).json()
    assert alerts["total"] == 1
    alert = alerts["items"][0]
    assert alert["project_name"] == "PRISM" and alert["environment_name"] == "Production"
    assert alert["resource_name"] == "app-prism-prod-uks"
    assert alert["current_value"] > alert["threshold"] == 70
    assert alert["unit"] == "percent"

    # Re-evaluating does not duplicate the alert.
    async with session_scope() as db:
        stats = await evaluate_alert_rules(db, get_azure_services(), uuid.UUID(me["organization_id"]))
    assert stats["fired"] == 0 and stats["unchanged"] == 1

    assert (
        await client.post(f"/api/v1/alerts/{alert['id']}/acknowledge", headers=auth_headers("viewer"))
    ).status_code == 403
    acked = await client.post(f"/api/v1/alerts/{alert['id']}/acknowledge", headers=auth_headers("operator"))
    assert acked.json()["status"] == "acknowledged"

    # Raising the threshold clears the condition and resolves the alert automatically.
    body = {
        k: rule[k]
        for k in (
            "name",
            "monitor_key",
            "metric_name",
            "aggregation",
            "operator",
            "severity",
            "window_minutes",
            "project_id",
            "environment_id",
        )
    }
    await client.put(
        f"/api/v1/alert-rules/{rule['id']}", json={**body, "threshold": 99.5}, headers=auth_headers("admin")
    )
    async with session_scope() as db:
        stats = await evaluate_alert_rules(db, get_azure_services(), uuid.UUID(me["organization_id"]))
    assert stats["resolved"] == 1
    detail = (await client.get(f"/api/v1/alerts/{alert['id']}", headers=auth_headers("viewer"))).json()
    assert detail["status"] == "resolved"
    assert [e["event_type"] for e in detail["events"]][::-1] == ["fired", "acknowledged", "resolved"]


async def test_rule_validation(client: httpx.AsyncClient) -> None:
    await seeded(client)
    bad = await client.post(
        "/api/v1/alert-rules",
        json={"name": "x", "monitor_key": "app_service", "metric_name": "not_a_metric", "threshold": 1},
        headers=auth_headers("admin"),
    )
    assert bad.status_code == 422
    denied = await client.post(
        "/api/v1/alert-rules",
        json={"name": "x", "monitor_key": "app_service", "metric_name": "plan_cpu", "threshold": 1},
        headers=auth_headers("operator"),
    )
    assert denied.status_code == 403


async def test_notifications_use_key_vault_reference(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await seeded(client)
    no_ref = await client.post(
        "/api/v1/notification-channels", json={"name": "Ops", "channel_type": "teams"}, headers=auth_headers("admin")
    )
    assert no_ref.status_code == 422
    url_in_config = await client.post(
        "/api/v1/notification-channels",
        json={
            "name": "Ops",
            "channel_type": "webhook",
            "secret_ref": "ops-hook",
            "config": {"url": "https://example.test/hook"},
        },
        headers=auth_headers("admin"),
    )
    assert url_in_config.status_code == 422
    channel = (
        await client.post(
            "/api/v1/notification-channels",
            json={"name": "Ops", "channel_type": "teams", "secret_ref": "org-0-ops-teams-hook"},
            headers=auth_headers("admin"),
        )
    ).json()

    sent: list[dict] = []

    async def fake_post(url: str, body: dict) -> None:
        sent.append({"url": url, "body": body})

    monkeypatch.setenv("SECRET_ORG_0_OPS_TEAMS_HOOK", "https://example.test/teams")
    monkeypatch.setattr("app.services.alerts.channels.registry._post", fake_post)

    test = (
        await client.post(f"/api/v1/notification-channels/{channel['id']}/test", headers=auth_headers("admin"))
    ).json()
    assert test["status"] == "sent"

    prod = next(e for e in data["prism"]["environments"] if e["slug"] == "prod")
    await _rule(
        client,
        project_id=data["prism"]["id"],
        environment_id=prod["id"],
        threshold=70,
        notification_channel_ids=[channel["id"]],
    )
    me = (await client.get("/api/v1/auth/me", headers=auth_headers("admin"))).json()
    import uuid

    from app.db.session import session_scope
    from app.services.alerts.evaluator import evaluate_alert_rules
    from app.services.azure.provider import get_azure_services

    async with session_scope() as db:
        await evaluate_alert_rules(db, get_azure_services(), uuid.UUID(me["organization_id"]))
    assert len(sent) == 2
    card = sent[1]["body"]["attachments"][0]["content"]
    assert "PRISM / Production" in card["body"][0]["text"]
    channels = (await client.get("/api/v1/notification-channels", headers=auth_headers("admin"))).json()
    assert "https://" not in str(channels)
