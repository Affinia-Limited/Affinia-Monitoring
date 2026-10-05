"""APIs behind the project-first dashboard: per-environment health, alerts, freshness, filters and search."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from tests.conftest import auth_headers
from tests.helpers import find_resource, seeded

VIEWER = auth_headers("viewer")


async def _fire_alert(
    client: httpx.AsyncClient, project: dict[str, Any], env_slug: str = "prod", threshold: float = 70
) -> int:
    from app.db.session import session_scope
    from app.services.alerts.evaluator import evaluate_alert_rules
    from app.services.azure.provider import get_azure_services

    env = next(e for e in project["environments"] if e["slug"] == env_slug)
    body = {
        "name": "High plan CPU",
        "monitor_key": "app_service",
        "metric_name": "plan_cpu",
        "aggregation": "Average",
        "operator": "gt",
        "threshold": threshold,
        "severity": "critical",
        "window_minutes": 15,
        "project_id": project["id"],
        "environment_id": env["id"],
    }
    assert (await client.post("/api/v1/alert-rules", json=body, headers=auth_headers("admin"))).status_code == 201
    me = (await client.get("/api/v1/auth/me", headers=auth_headers("admin"))).json()
    async with session_scope() as db:
        stats = await evaluate_alert_rules(db, get_azure_services(), uuid.UUID(me["organization_id"]))
    assert stats["fired"] >= 1
    return int(stats["fired"])


async def test_projects_report_monitored_health_alerts_and_freshness_per_environment(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    await _fire_alert(client, data["prism"])
    projects = {p["name"]: p for p in (await client.get("/api/v1/projects", headers=VIEWER)).json()}
    prism = projects["PRISM"]
    envs = {e["slug"]: e for e in prism["environments"]}
    assert envs["prod"]["active_alerts"] == 1 and envs["dev"]["active_alerts"] == 0
    assert prism["active_alerts"] == 1
    assert envs["prod"]["last_checked_at"] and prism["last_checked_at"]
    # Environment counts add up to the project's, and cover monitored resources only.
    assert sum(e["health"]["total"] for e in prism["environments"]) <= prism["health"]["total"]
    monitored = (
        await client.get(
            "/api/v1/resources",
            params={"project_id": prism["id"], "monitored_only": True, "page_size": 1},
            headers=VIEWER,
        )
    ).json()["total"]
    assert prism["health"]["total"] == monitored


async def test_overview_summarises_environments_and_data_freshness(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    fired = await _fire_alert(client, data["crm"], threshold=0.001)
    body = (await client.get("/api/v1/overview", headers=VIEWER)).json()
    assert sum(body["environment_health"].values()) == body["totals"]["environments"] == 5
    assert body["last_synced_at"] and body["generated_at"]
    crm = next(p for p in body["project_health"] if p["name"] == "CRM")
    assert crm["active_alerts"] == fired and "description" in crm
    prod = next(e for e in crm["environments"] if e["slug"] == "prod")
    assert prod["active_alerts"] == fired and prod["last_checked_at"]
    assert body["alerts"]["active"] == fired


async def test_health_evaluation_keeps_every_rule_reading(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    detail = (await client.get(f"/api/v1/resources/{app['id']}", headers=VIEWER)).json()
    readings = detail["health_metrics"]
    assert readings, "health readings are stored during evaluation"
    assert {"metric", "label", "unit", "value", "status", "window_minutes"} <= set(readings[0])
    # Healthy readings are kept too, not only breaching ones.
    statuses = {r["status"] for r in readings}
    assert statuses & {"healthy", "warning", "critical"}
    breaching = {r["metric"] for r in detail["health_reasons"] if r.get("signal") == "metric"}
    assert breaching <= {r["metric"] for r in readings}
    listed = (await client.get("/api/v1/resources", params={"q": "app-crm-prod-uks"}, headers=VIEWER)).json()["items"][
        0
    ]
    assert listed["health_metrics"] == readings and listed["active_alerts"] == 0


async def test_alert_filters(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    await _fire_alert(client, data["prism"])

    async def total(**params: object) -> int:
        return (await client.get("/api/v1/alerts", params={"status": "open", **params}, headers=VIEWER)).json()["total"]

    assert await total() == 1
    assert await total(q="app-prism-prod") == 1
    assert await total(q="plan cpu") == 1
    assert await total(q="no-such-thing") == 0
    assert await total(q="%") == 0  # LIKE wildcards are escaped
    assert await total(monitor_key="app_service") == 1
    assert await total(monitor_key="sql_database") == 0
    assert await total(since_hours=1) == 1
    assert (await client.get("/api/v1/alerts", params={"since_hours": 0}, headers=VIEWER)).status_code == 422


async def test_facets_can_exclude_inventory(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    params = {"project_id": data["crm"]["id"]}
    everything = (await client.get("/api/v1/resources/facets", params=params, headers=VIEWER)).json()
    monitored = (
        await client.get("/api/v1/resources/facets", params={**params, "monitored_only": True}, headers=VIEWER)
    ).json()
    assert sum(h["count"] for h in monitored["health"]) <= sum(h["count"] for h in everything["health"])


async def test_search_understands_project_environment_terms_and_gives_context(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    await _fire_alert(client, data["crm"], threshold=0.001)

    async def hits(q: str) -> list[dict[str, Any]]:
        return (await client.get("/api/v1/search", params={"q": q}, headers=VIEWER)).json()["hits"]

    found = await hits("crm-prod")
    kinds = {h["kind"] for h in found}
    assert {"project", "environment", "resource", "logs"} <= kinds
    env = next(h for h in found if h["kind"] == "environment")
    prod = next(e for e in data["crm"]["environments"] if e["slug"] == "prod")
    assert env["title"] == "CRM / Production"
    assert env["url"] == f"/projects/{data['crm']['id']}/environments/{prod['id']}"
    # Only the project's matching environment, not every environment of the project.
    assert [h["title"] for h in found if h["kind"] == "environment"] == ["CRM / Production"]
    resource = next(h for h in found if h["title"] == "app-crm-prod-uks")
    assert resource["project_name"] == "CRM" and resource["environment_name"] == "Production"
    assert resource["type_display_name"] == "App Service" and resource["health_status"]

    alerts = [h for h in await hits("app-crm-prod-uks") if h["kind"] == "alert"]
    assert alerts and alerts[0]["severity"] == "critical" and alerts[0]["url"].startswith("/alerts?alert=")


async def test_log_targets_carry_project_and_environment_ids(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    targets = (await client.get("/api/v1/logs/targets", headers=auth_headers("operator"))).json()
    crm_targets = [t for t in targets if t["project_name"] == "CRM"]
    assert crm_targets and all(t["project_id"] == data["crm"]["id"] for t in crm_targets)
    assert all(t["environment_id"] for t in crm_targets if t["environment_name"])


async def test_dashboard_apis_stay_organisation_scoped(client: httpx.AsyncClient) -> None:
    from tests.conftest import OTHER_TENANT

    await seeded(client)
    other = auth_headers("super_admin", tenant=OTHER_TENANT)
    assert (await client.get("/api/v1/projects", headers=other)).json() == []
    assert (await client.get("/api/v1/search", params={"q": "crm-prod"}, headers=other)).json()["hits"] == []
    assert (await client.get("/api/v1/alerts", params={"q": "crm"}, headers=other)).json()["total"] == 0
    overview = (await client.get("/api/v1/overview", headers=other)).json()
    assert overview["project_health"] == [] and overview["environment_health"]["healthy"] == 0


async def test_project_views_do_not_scale_queries_with_project_count(client: httpx.AsyncClient) -> None:
    """20+ projects with several environments each must not cause N+1 queries."""
    from sqlalchemy import event

    from app.db.session import get_engine
    from tests.helpers import create_project

    statements: list[str] = []

    def count(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        statements.append(statement)

    async def queries_for(path: str) -> int:
        statements.clear()
        event.listen(get_engine().sync_engine, "before_cursor_execute", count)
        try:
            assert (await client.get(path, headers=VIEWER)).status_code == 200
        finally:
            event.remove(get_engine().sync_engine, "before_cursor_execute", count)
        return len(statements)

    await create_project(client, "p0")
    await client.get("/api/v1/auth/me", headers=VIEWER)  # first request records the sign-in
    small = {path: await queries_for(path) for path in ("/api/v1/projects", "/api/v1/overview")}
    for i in range(1, 25):
        await create_project(client, f"p{i}")
    for path, before in small.items():
        assert await queries_for(path) == before, path
    assert len((await client.get("/api/v1/projects", headers=VIEWER)).json()) == 25
