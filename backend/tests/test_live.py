"""Live endpoint: current status and minute-by-minute health metrics."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.azure.provider import get_azure_services
from tests.conftest import auth_headers
from tests.helpers import find_resource, seeded

_RANK = {"critical": 0, "warning": 1, "healthy": 2, "unknown": 3}


async def _live(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get("/api/v1/live", params=params, headers=auth_headers("viewer"))
    assert response.status_code == 200, response.text
    return response.json()


async def test_live_returns_status_and_minute_metrics(client: httpx.AsyncClient) -> None:
    await seeded(client)
    body = await _live(client)

    assert body["is_mock"] is True
    assert body["window_minutes"] == 60 and body["interval_seconds"] == 60
    assert body["health"]["total"] == body["resources_total"] > 0
    assert {(e["project_name"], e["environment_name"]) for e in body["environments"]} >= {
        ("CRM", "Production"),
        ("PRISM", "Production"),
    }

    resources = body["resources"]
    assert 0 < len(resources) <= 24
    # Worst health first, so the resources that need attention are always included.
    ranks = [_RANK[r["health_status"]] for r in resources]
    assert ranks == sorted(ranks)

    app = next(r for r in resources if r["name"] == "app-crm-prod-uks")
    assert (app["project_name"], app["environment_name"]) == ("CRM", "Production")
    metrics = {m["key"]: m for m in app["metrics"]}
    assert 0 < len(metrics) <= 3
    plan_cpu = metrics["plan_cpu"]
    assert plan_cpu["unit"] == "percent"
    assert len(plan_cpu["points"]) >= 55  # one point per minute over the last hour
    assert plan_cpu["latest"] is not None and plan_cpu["window_value"] is not None
    assert (plan_cpu["warning"], plan_cpu["critical"], plan_cpu["operator"]) == (80, 90, "gt")
    assert plan_cpu["status"] in ("healthy", "warning", "critical")


async def test_live_scopes_to_project_and_environment(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    crm = data["crm"]
    prod = next(e for e in crm["environments"] if e["slug"] == "prod")

    by_project = await _live(client, project_id=crm["id"])
    assert {e["project_id"] for e in by_project["environments"]} == {crm["id"]}
    assert len(by_project["environments"]) == 3
    assert by_project["resources"] and all(r["project_id"] == crm["id"] for r in by_project["resources"])
    assert all(a["project_id"] == crm["id"] for a in by_project["recent_alerts"])

    by_env = await _live(client, project_id=crm["id"], environment_id=prod["id"])
    assert [e["environment_id"] for e in by_env["environments"]] == [prod["id"]]
    assert all(r["environment_id"] == prod["id"] for r in by_env["resources"])
    assert by_env["resources_total"] <= by_project["resources_total"] <= (await _live(client))["resources_total"]


async def test_live_applies_threshold_overrides(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    plan = await find_resource(client, "asp-crm-prod-uks")
    for body in (
        {"monitor_key": "app_service_plan", "metric_name": "cpu", "warning_threshold": 0, "critical_threshold": 1},
        {"monitor_key": "app_service_plan", "metric_name": "memory", "enabled": False},
    ):
        response = await client.put("/api/v1/health-rules", json=body, headers=auth_headers("super_admin"))
        assert response.status_code == 200, response.text

    crm_prod = next(e for e in data["crm"]["environments"] if e["slug"] == "prod")
    body = await _live(client, project_id=data["crm"]["id"], environment_id=crm_prod["id"])
    live_plan = next(r for r in body["resources"] if r["id"] == plan["id"])
    metrics = {m["key"]: m for m in live_plan["metrics"]}
    assert metrics["cpu"]["status"] == "critical" and metrics["cpu"]["critical"] == 1
    assert "memory" not in metrics


async def test_live_reads_azure_once_per_minute_for_all_viewers(client: httpx.AsyncClient, monkeypatch: Any) -> None:
    await seeded(client)
    metrics = get_azure_services().metrics
    calls = 0
    original = metrics.query

    async def counting(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(metrics, "query", counting)
    first = await _live(client)
    after_first = calls
    second = await _live(client)
    assert after_first > 0
    # The window is aligned to the minute, so a second poll in the same minute is served from the cache.
    if first["generated_at"][:16] == second["generated_at"][:16]:
        assert calls == after_first


async def test_live_requires_dashboard_access(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/live")).status_code == 401
    empty = await _live(client)
    assert empty["resources"] == [] and empty["environments"] == [] and empty["health"]["total"] == 0
