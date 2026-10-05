"""MetricService, dashboards generated from templates, and environment comparison."""

from __future__ import annotations

import httpx
import pytest

from app.services.azure.types import TimeRange
from app.services.monitors.registry import all_monitors, resolve_monitor, validate_all
from tests.conftest import auth_headers
from tests.helpers import find_resource, seeded


def test_all_monitor_templates_are_valid() -> None:
    validate_all()
    for monitor in all_monitors():
        template = monitor.template()
        assert template["sections"], monitor.key


@pytest.mark.parametrize(
    ("rtype", "kind", "sku", "expected"),
    [
        ("microsoft.web/sites", "app,linux", None, "app_service"),
        ("microsoft.web/sites", "functionapp,linux", None, "function_app"),
        ("microsoft.cdn/profiles", None, "Premium_AzureFrontDoor", "front_door"),
        ("microsoft.cdn/profiles", None, "Standard_Microsoft", "generic"),
        ("microsoft.network/frontdoors", None, None, "front_door_classic"),
        ("microsoft.sql/servers/databases", None, "System", "generic"),
        ("microsoft.sql/servers/databases", "v12.0,system,serverless", "GP_SYSTEM", "generic"),
        ("microsoft.sql/servers/databases", "v12.0,user,vcore,serverless", "GP_S_Gen5", "sql_database"),
        ("microsoft.sql/servers/databases", None, "S2", "sql_database"),
        ("microsoft.unknown/things", None, None, "generic"),
    ],
)
def test_monitor_resolution(rtype: str, kind: str | None, sku: str | None, expected: str) -> None:
    assert resolve_monitor(rtype, kind, sku).key == expected


def test_time_range_intervals() -> None:
    assert TimeRange.from_params("1h").auto_interval().total_seconds() == 60
    assert TimeRange.from_params("24h").auto_interval().total_seconds() == 30 * 60
    assert TimeRange.from_params("30d").auto_interval().total_seconds() == 12 * 3600


async def test_metrics_endpoint_normalises_and_scales(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    response = await client.get(
        f"/api/v1/resources/{app['id']}/metrics",
        params={"metrics": "requests,response_time,plan_cpu", "timeRange": "6h"},
        headers=auth_headers("viewer"),
    )
    assert response.status_code == 200, response.text
    metrics = {m["key"]: m for m in response.json()["metrics"]}
    assert metrics["requests"]["unit"] == "count"
    assert metrics["requests"]["is_mock"] is True
    # HttpResponseTime is reported in seconds by Azure and scaled to milliseconds.
    assert metrics["response_time"]["unit"] == "milliseconds"
    assert 20 < metrics["response_time"]["summary"]["avg"] < 1000
    # Plan CPU is read from the related App Service Plan.
    plan = await find_resource(client, "asp-crm-prod-uks")
    assert metrics["plan_cpu"]["source_resource_id"] == plan["id"]
    assert len(metrics["plan_cpu"]["series"][0]["points"]) > 10


async def test_split_metrics_return_one_series_per_dimension(client: httpx.AsyncClient) -> None:
    await seeded(client)
    afd = await find_resource(client, "afd-crm-prod")
    response = await client.get(
        f"/api/v1/resources/{afd['id']}/metrics",
        params={"metrics": "requests_by_status", "timeRange": "1h"},
        headers=auth_headers("viewer"),
    )
    series = response.json()["metrics"][0]["series"]
    assert {s["name"] for s in series} == {"2xx", "3xx", "4xx", "5xx"}


async def test_unknown_metric_and_bad_time_range(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    r = await client.get(
        f"/api/v1/resources/{app['id']}/metrics", params={"metrics": "nope"}, headers=auth_headers("viewer")
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "METRIC_NOT_FOUND"
    r = await client.get(
        f"/api/v1/resources/{app['id']}/metrics",
        params={"metrics": "requests", "timeRange": "5y"},
        headers=auth_headers("viewer"),
    )
    assert r.status_code == 422
    r = await client.get(
        f"/api/v1/resources/{app['id']}/metrics",
        params={
            "metrics": "requests",
            "timeRange": "custom",
            "start": "2026-01-10T00:00:00Z",
            "end": "2026-01-01T00:00:00Z",
        },
        headers=auth_headers("viewer"),
    )
    assert r.status_code == 422


async def test_missing_related_resource_reports_unavailable(client: httpx.AsyncClient) -> None:
    await seeded(client)
    func = await find_resource(client, "app-crm-dev-uks")
    from sqlalchemy import select

    from app.db.session import get_sessionmaker
    from app.models import Resource

    async with get_sessionmaker()() as session:
        row = await session.scalar(select(Resource).where(Resource.name == "app-crm-dev-uks"))
        assert row is not None
        row.properties = {
            **row.properties,
            "serverFarmId": "/subscriptions/x/resourcegroups/y/providers/microsoft.web/serverfarms/missing",
        }
        await session.commit()
    response = await client.get(
        f"/api/v1/resources/{func['id']}/metrics",
        params={"metrics": "plan_cpu,requests"},
        headers=auth_headers("viewer"),
    )
    metrics = {m["key"]: m for m in response.json()["metrics"]}
    assert metrics["plan_cpu"]["unavailable_reason"] == "RELATED_RESOURCE_NOT_FOUND"
    assert metrics["requests"]["unavailable_reason"] is None


async def test_dashboards_generated_per_type(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    dashboard = (await client.get(f"/api/v1/dashboards/by-resource/{app['id']}", headers=auth_headers("viewer"))).json()
    assert dashboard["sections"] == ["Overview", "HTTP", "Resources", "Application Insights", "Logs"]
    types = {w["widget_type"] for w in dashboard["widgets"]}
    assert {"gauge", "line_chart", "bar_chart", "log_table", "alert_table", "resource_health"} <= types

    sql = await find_resource(client, "sqldb-crm-prod")
    sql_dash = (await client.get(f"/api/v1/dashboards/by-resource/{sql['id']}", headers=auth_headers("viewer"))).json()
    assert "Query performance" in sql_dash["sections"]

    afd = await find_resource(client, "afd-crm-prod")
    afd_dash = (await client.get(f"/api/v1/dashboards/by-resource/{afd['id']}", headers=auth_headers("viewer"))).json()
    assert {"Overview", "Origins", "Traffic", "Security"} == set(afd_dash["sections"])

    listing = (await client.get("/api/v1/dashboards", headers=auth_headers("viewer"))).json()
    assert all(d["type_display_name"] != "virtualNetworks" for d in listing)


async def test_customised_dashboard_is_preserved_and_resettable(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    dashboard = (await client.get(f"/api/v1/dashboards/by-resource/{app['id']}", headers=auth_headers("viewer"))).json()
    widgets = [
        {
            "section": "Overview",
            "widget_type": "line_chart",
            "title": "CPU only",
            "width": 12,
            "config": {"metrics": ["plan_cpu"]},
        }
    ]
    r = await client.patch(
        f"/api/v1/dashboards/{dashboard['id']}", json={"widgets": widgets}, headers=auth_headers("admin")
    )
    assert r.status_code == 200 and r.json()["is_customized"] is True
    bad = await client.patch(
        f"/api/v1/dashboards/{dashboard['id']}",
        json={"widgets": [{**widgets[0], "config": {"metrics": ["bogus"]}}]},
        headers=auth_headers("admin"),
    )
    assert bad.status_code == 422
    assert (
        await client.patch(
            f"/api/v1/dashboards/{dashboard['id']}", json={"widgets": widgets}, headers=auth_headers("viewer")
        )
    ).status_code == 403
    reset = await client.post(f"/api/v1/dashboards/{dashboard['id']}/reset", headers=auth_headers("admin"))
    assert reset.json()["is_customized"] is False
    assert len(reset.json()["widgets"]) > 10


async def test_environment_comparison(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    response = await client.get(
        f"/api/v1/projects/{data['crm']['id']}/comparison", params={"timeRange": "24h"}, headers=auth_headers("viewer")
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [e["name"] for e in body["environments"]] == ["Development", "UAT", "Production"]
    labels = {row["label"] for row in body["rows"]}
    assert {"CPU", "Requests", "5xx", "Response time", "SQL CPU", "Front Door requests"} <= labels
    fd = next(r for r in body["rows"] if r["label"] == "Front Door requests")
    dev = next(e["id"] for e in body["environments"] if e["name"] == "Development")
    assert fd["values"][dev] is None and fd["resource_counts"][dev] == 0


async def test_gauges_carry_health_thresholds_and_templates_upgrade(client: httpx.AsyncClient) -> None:
    await seeded(client)
    afd = await find_resource(client, "afd-crm-prod")
    dash = (await client.get(f"/api/v1/dashboards/by-resource/{afd['id']}", headers=auth_headers("viewer"))).json()
    origin = next(w for w in dash["widgets"] if w["title"] == "Origin health")
    assert origin["config"]["thresholds"] == {"operator": "lt", "warning": 90, "critical": 50}
    requests = next(w for w in dash["widgets"] if w["title"] == "Requests")
    assert "thresholds" not in requests["config"]

    # A changed template definition bumps the stored version and rebuilds non-customised dashboards.
    from sqlalchemy import select

    from app.db.session import session_scope
    from app.models import DashboardTemplate
    from app.services.dashboards.generator import generate_dashboards

    async with session_scope() as db:
        template = await db.scalar(select(DashboardTemplate).where(DashboardTemplate.key == "front_door.default"))
        assert template is not None
        old_version = template.version
        template.definition = {"sections": []}
    me = (await client.get("/api/v1/auth/me", headers=auth_headers("admin"))).json()
    import uuid

    async with session_scope() as db:
        stats = await generate_dashboards(db, uuid.UUID(me["organization_id"]))
    assert stats["dashboards_updated"] >= 1
    async with session_scope() as db:
        template = await db.scalar(select(DashboardTemplate).where(DashboardTemplate.key == "front_door.default"))
        assert template is not None and template.version == old_version + 1
