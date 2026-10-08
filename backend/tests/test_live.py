"""Live mode: per-resource status and minute-by-minute health metrics."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.services.azure.provider import get_azure_services
from tests.conftest import OTHER_TENANT, auth_headers
from tests.helpers import find_resource, seeded


async def _live(client: httpx.AsyncClient, *ids: str, role: str = "viewer", **headers: Any) -> dict[str, Any]:
    response = await client.get(
        "/api/v1/live/resources", params={"ids": ",".join(ids)}, headers=headers or auth_headers(role)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_live_resource_metrics_and_status(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    body = await _live(client, app["id"])

    assert body["is_mock"] is True
    assert body["window_minutes"] == 60 and body["interval_seconds"] == 60
    live = body["resources"][app["id"]]
    assert live["evaluated_status"] == app["health_status"]
    metrics = {m["key"]: m for m in live["metrics"]}
    # Every health rule of the App Service monitor, in rule order.
    assert list(metrics) == ["plan_cpu", "plan_memory", "http5xx", "response_time", "health_check"]
    plan_cpu = metrics["plan_cpu"]
    assert plan_cpu["unit"] == "percent"
    assert len(plan_cpu["values"]) >= 55  # one value per minute over the last hour
    assert plan_cpu["latest"] is not None and plan_cpu["window_value"] is not None
    assert (plan_cpu["warning"], plan_cpu["critical"], plan_cpu["operator"]) == (80, 90, "gt")
    assert live["status"] in ("healthy", "warning", "critical")
    # Every live breach is explained in the same shape as a stored health reason.
    breaching = {m["key"] for m in live["metrics"] if m["status"] in ("warning", "critical")}
    assert {r["metric"] for r in live["reasons"] if r["signal"] == "metric"} == breaching


async def test_live_status_follows_live_metrics(client: httpx.AsyncClient) -> None:
    await seeded(client)
    plan = await find_resource(client, "asp-crm-prod-uks")
    before = (await _live(client, plan["id"]))["resources"][plan["id"]]
    assert before["status"] != "critical"

    # Tighten the CPU threshold: the live status turns critical without a health evaluation.
    response = await client.put(
        "/api/v1/health-rules",
        json={"monitor_key": "app_service_plan", "metric_name": "cpu", "warning_threshold": 0, "critical_threshold": 1},
        headers=auth_headers("super_admin"),
    )
    assert response.status_code == 200, response.text
    after = (await _live(client, plan["id"]))["resources"][plan["id"]]
    assert after["status"] == "critical"
    assert after["evaluated_status"] == plan["health_status"]
    reason = next(r for r in after["reasons"] if r["metric"] == "cpu")
    assert reason["severity"] == "critical" and reason["threshold"] == 1


async def test_live_keeps_resource_health_signals(client: httpx.AsyncClient) -> None:
    await seeded(client)
    # The mock reports Resource Health "Degraded" for this app; live metrics cannot clear that.
    app = await find_resource(client, "app-prism-prod-uks")
    live = (await _live(client, app["id"]))["resources"][app["id"]]
    assert any(r["signal"] == "resource_health" for r in live["reasons"])
    assert live["status"] in ("warning", "critical")


async def test_live_disabled_rules_are_skipped(client: httpx.AsyncClient) -> None:
    await seeded(client)
    plan = await find_resource(client, "asp-crm-prod-uks")
    response = await client.put(
        "/api/v1/health-rules",
        json={"monitor_key": "app_service_plan", "metric_name": "memory", "enabled": False},
        headers=auth_headers("super_admin"),
    )
    assert response.status_code == 200, response.text
    live = (await _live(client, plan["id"]))["resources"][plan["id"]]
    assert [m["key"] for m in live["metrics"]] == ["cpu"]


async def test_live_batches_and_caches_azure_reads(client: httpx.AsyncClient, monkeypatch: Any) -> None:
    await seeded(client)
    ids = [(await find_resource(client, n))["id"] for n in ("app-crm-prod-uks", "asp-crm-prod-uks", "sqldb-prism-prod")]
    metrics = get_azure_services().metrics
    calls: list[int] = []
    original = metrics.query

    async def counting(tenant_id: str, azure_id: str, requests: list[Any], *args: Any, **kwargs: Any) -> Any:
        calls.append(len(requests))
        return await original(tenant_id, azure_id, requests, *args, **kwargs)

    monkeypatch.setattr(metrics, "query", counting)
    first = await _live(client, *ids)
    metric_count = sum(len(r["metrics"]) for r in first["resources"].values())
    # Several metrics per Azure request rather than one request per metric.
    assert 0 < len(calls) < metric_count
    assert sum(calls) <= metric_count
    made = len(calls)
    second = await _live(client, *ids)
    # The window is aligned to the minute, so a second poll in the same minute is served from the cache.
    if first["generated_at"][:16] == second["generated_at"][:16]:
        assert len(calls) == made


async def test_live_scope_and_validation(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    vnet = await find_resource(client, "vnet-crm-prod-uks")

    # Inventory items have no live signals; unknown ids are ignored.
    body = await _live(client, app["id"], vnet["id"], str(uuid.uuid4()))
    assert list(body["resources"]) == [app["id"]]
    # Another organisation cannot read this one's resources.
    other = await _live(client, app["id"], **auth_headers("viewer", tenant=OTHER_TENANT))
    assert other["resources"] == {}

    assert (await client.get("/api/v1/live/resources", params={"ids": app["id"]})).status_code == 401
    bad = await client.get("/api/v1/live/resources", params={"ids": "nope"}, headers=auth_headers("viewer"))
    assert bad.status_code == 422
    many = ",".join(str(uuid.uuid4()) for _ in range(51))
    too_many = await client.get("/api/v1/live/resources", params={"ids": many}, headers=auth_headers("viewer"))
    assert too_many.status_code == 422
