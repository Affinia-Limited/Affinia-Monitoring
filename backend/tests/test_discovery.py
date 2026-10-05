"""Azure connection, discovery and synchronisation."""

from __future__ import annotations

from dataclasses import replace

import httpx

from app.core.errors import AzurePermissionDeniedError
from app.services.azure.mock.services import MockLogsService, MockMetricsService, MockResourceGraphService
from app.services.azure.provider import set_azure_services
from app.services.azure.types import AzureServices
from tests.conftest import auth_headers
from tests.helpers import SUB_A, SUB_B, connect, create_project, find_resource, seeded


async def test_connect_runs_all_steps_and_discovers(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    run = (await client.get(f"/api/v1/azure/sync-runs/{data['run']['id']}", headers=auth_headers("viewer"))).json()
    assert run["status"] == "succeeded", run
    assert [s["status"] for s in run["steps"]] == ["succeeded"] * 7
    assert run["stats"]["created"] > 20
    assert run["stats"]["dashboards_created"] == run["stats"]["created"]

    conn = (
        await client.get(f"/api/v1/azure/connections/{data['connection']['id']}", headers=auth_headers("viewer"))
    ).json()
    assert conn["status"] == "connected"
    assert conn["resource_count"] == run["stats"]["created"]
    assert conn["subscriptions"][0]["display_name"] == "Demo - Line of Business"


async def test_resource_types_categorised(client: httpx.AsyncClient) -> None:
    await seeded(client)
    expectations = {
        "app-crm-prod-uks": "app_service",
        "asp-crm-prod-uks": "app_service_plan",
        "sqldb-crm-prod": "sql_database",
        "sql-crm-prod-uks": "sql_server",
        "afd-crm-prod": "front_door",
        "appi-crm-prod-uks": "app_insights",
        "acrcrmproduks": "container_registry",
        "vnet-crm-prod-uks": "generic",
    }
    for name, key in expectations.items():
        assert (await find_resource(client, name))["monitor_key"] == key, name
    # The system 'master' database is discovered but not given a SQL monitor.
    masters = (await client.get("/api/v1/resources", params={"q": "master"}, headers=auth_headers("viewer"))).json()
    assert all(r["monitor_key"] == "generic" for r in masters["items"])


async def test_tags_map_to_projects_and_environments(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    resource = await find_resource(client, "app-prism-prod-uks")
    assert resource["project_id"] == data["prism"]["id"]
    assert resource["environment_name"] == "Production"
    assert resource["assignment_source"] == "tag"


async def test_connection_defaults_used_when_tags_do_not_match(client: httpx.AsyncClient) -> None:
    project = await create_project(client, "shared", envs=("prod",))
    env_id = project["environments"][0]["id"]
    await connect(client, default_project_id=project["id"], default_environment_id=env_id)
    resource = await find_resource(client, "app-crm-dev-uks")
    assert resource["project_id"] == project["id"]
    assert resource["environment_id"] == env_id
    assert resource["assignment_source"] == "connection_default"


async def test_resync_is_idempotent_and_tracks_removals(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    before = (await client.get("/api/v1/resources", headers=auth_headers("viewer"))).json()["total"]

    # Manual assignment must survive sync.
    target = await find_resource(client, "kv-crm-dev-uks")
    prism_prod = next(e for e in data["prism"]["environments"] if e["slug"] == "prod")
    r = await client.put(
        f"/api/v1/resources/{target['id']}/assignment",
        json={"project_id": data["prism"]["id"], "environment_id": prism_prod["id"]},
        headers=auth_headers("admin"),
    )
    assert r.status_code == 200

    class Shrinking(MockResourceGraphService):
        async def discover_resources(self, tenant_id, subscription_ids):  # type: ignore[no-untyped-def]
            items = await super().discover_resources(tenant_id, subscription_ids)
            return [replace(i, tags={**i.tags, "owner": "team-a"}) for i in items if i.name != "stcrmdevuks"]

    set_azure_services(AzureServices(Shrinking(), MockMetricsService(), MockLogsService(), is_mock=True))
    run = (
        await client.post(
            f"/api/v1/azure/connections/{data['connection']['id']}/sync", headers=auth_headers("operator")
        )
    ).json()
    from app.services.jobs import wait_for_inline_jobs

    await wait_for_inline_jobs()
    run = (await client.get(f"/api/v1/azure/sync-runs/{run['id']}", headers=auth_headers("viewer"))).json()
    assert run["status"] == "succeeded", run
    assert run["stats"]["created"] == 0
    assert run["stats"]["removed"] == 1

    after = (await client.get("/api/v1/resources", headers=auth_headers("viewer"))).json()["total"]
    assert after == before - 1
    kv = await find_resource(client, "kv-crm-dev-uks")
    assert kv["project_id"] == data["prism"]["id"] and kv["assignment_source"] == "manual"
    assert kv["tags"]["owner"] == "team-a"

    # The resource comes back when it reappears in Azure.
    set_azure_services(None)
    await client.post(f"/api/v1/azure/connections/{data['connection']['id']}/sync", headers=auth_headers("operator"))
    await wait_for_inline_jobs()
    assert (await client.get("/api/v1/resources", headers=auth_headers("viewer"))).json()["total"] == before


async def test_duplicate_subscription_rejected(client: httpx.AsyncClient) -> None:
    await connect(client)
    response = await client.post(
        "/api/v1/azure/connections",
        json={"name": "again", "tenant_id": "00000000-0000-4000-8000-00000000d3a0", "subscription_ids": [SUB_A]},
        headers=auth_headers("admin"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SUBSCRIPTION_ALREADY_CONNECTED"


async def test_add_second_subscription_without_code_changes(client: httpx.AsyncClient) -> None:
    await create_project(client, "datacore")
    await connect(client, [SUB_A])
    created = await connect(client, [SUB_B])
    assert created["sync_run"]["status"] == "queued"
    resource = await find_resource(client, "func-datacore-prod-uks")
    assert resource["monitor_key"] == "function_app"
    assert resource["project_name"] == "DATACORE"


async def test_permission_failure_is_reported_per_step(client: httpx.AsyncClient) -> None:
    class Denied(MockResourceGraphService):
        async def discover_resource_groups(self, tenant_id, subscription_ids):  # type: ignore[no-untyped-def]
            raise AzurePermissionDeniedError()

    set_azure_services(AzureServices(Denied(), MockMetricsService(), MockLogsService(), is_mock=True))
    created = await connect(client)
    run = (
        await client.get(f"/api/v1/azure/sync-runs/{created['sync_run']['id']}", headers=auth_headers("viewer"))
    ).json()
    assert run["status"] == "failed"
    assert run["error_code"] == "AZURE_PERMISSION_DENIED"
    statuses = {s["key"]: s["status"] for s in run["steps"]}
    assert statuses["subscriptions"] == "succeeded"
    assert statuses["permissions"] == "failed"
    assert statuses["discover"] == "skipped"
    conn = (await client.get("/api/v1/azure/connections", headers=auth_headers("viewer"))).json()[0]
    assert conn["status"] == "error"
    assert conn["last_error_code"] == "AZURE_PERMISSION_DENIED"


async def test_disconnect_archives_resources_and_allows_reconnect(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    response = await client.delete(
        f"/api/v1/azure/connections/{data['connection']['id']}", headers=auth_headers("admin")
    )
    assert response.status_code == 204
    assert (await client.get("/api/v1/resources", headers=auth_headers("viewer"))).json()["total"] == 0
    await connect(client)
    assert (await client.get("/api/v1/resources", headers=auth_headers("viewer"))).json()["total"] > 0


async def test_connection_payload_never_contains_credentials(client: httpx.AsyncClient) -> None:
    body = {
        "name": "x",
        "tenant_id": "00000000-0000-4000-8000-00000000d3a0",
        "subscription_ids": [SUB_A],
        "client_secret": "should-be-ignored",
    }
    response = await client.post("/api/v1/azure/connections", json=body, headers=auth_headers("admin"))
    assert response.status_code == 202
    assert "should-be-ignored" not in response.text
    from sqlalchemy import select

    from app.db.session import get_sessionmaker
    from app.models import AuditLog, AzureConnection

    async with get_sessionmaker()() as session:
        conn = await session.scalar(select(AzureConnection))
        assert conn is not None
        stored = {column.name: getattr(conn, column.name) for column in conn.__table__.columns}
        assert "should-be-ignored" not in str(stored)
        audits = list(await session.scalars(select(AuditLog)))
        assert "should-be-ignored" not in str([a.details for a in audits])
