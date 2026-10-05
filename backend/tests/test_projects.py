from __future__ import annotations

import httpx

from tests.conftest import auth_headers
from tests.helpers import create_project, find_resource, seeded


async def test_create_and_list_projects(client: httpx.AsyncClient) -> None:
    project = await create_project(client, "crm")
    assert [e["slug"] for e in project["environments"]] == ["dev", "uat", "prod"]
    listing = (await client.get("/api/v1/projects", headers=auth_headers("viewer"))).json()
    assert [p["slug"] for p in listing] == ["crm"]


async def test_duplicate_slug_conflicts(client: httpx.AsyncClient) -> None:
    await create_project(client, "crm")
    response = await client.post("/api/v1/projects", json={"name": "CRM", "slug": "crm"}, headers=auth_headers("admin"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROJECT_EXISTS"


async def test_invalid_slug_rejected_without_echoing_input(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects", json={"name": "CRM", "slug": "Not A Slug!"}, headers=auth_headers("admin")
    )
    assert response.status_code == 422
    assert "Not A Slug" not in response.text


async def test_environment_crud(client: httpx.AsyncClient) -> None:
    project = await create_project(client, "crm", envs=("dev",))
    created = await client.post(
        f"/api/v1/projects/{project['id']}/environments",
        json={"name": "Production", "slug": "prod", "kind": "production"},
        headers=auth_headers("admin"),
    )
    assert created.status_code == 201
    env_id = created.json()["id"]
    updated = await client.patch(
        f"/api/v1/projects/{project['id']}/environments/{env_id}",
        json={"tag_values": ["live"]},
        headers=auth_headers("admin"),
    )
    assert updated.json()["tag_values"] == ["live"]
    deleted = await client.delete(
        f"/api/v1/projects/{project['id']}/environments/{env_id}", headers=auth_headers("admin")
    )
    assert deleted.status_code == 204
    detail = (await client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers("viewer"))).json()
    assert [e["slug"] for e in detail["environments"]] == ["dev"]


async def test_project_health_rollup_and_delete(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    detail = (await client.get(f"/api/v1/projects/{data['crm']['id']}", headers=auth_headers("viewer"))).json()
    assert detail["health"]["total"] > 0
    assert {e["slug"] for e in detail["environments"]} == {"dev", "uat", "prod"}

    response = await client.delete(f"/api/v1/projects/{data['crm']['id']}", headers=auth_headers("admin"))
    assert response.status_code == 204
    resource = await find_resource(client, "app-crm-prod-uks")
    assert resource["project_id"] is None
    # The slug can be reused after deletion.
    await create_project(client, "crm")


async def test_add_project_without_code_changes_maps_on_next_sync(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    await create_project(client, "internal", envs=("dev", "prod"))
    # A different subscription hosts the INTERNAL demo workload.
    from tests.helpers import connect

    await connect(client, ["33333333-3333-4333-8333-333333333333"])
    resource = await find_resource(client, "app-internal-prod-uks")
    assert resource["project_name"] == "INTERNAL"
    assert resource["environment_name"] == "Production"
    assert data["crm"]["id"] != resource["project_id"]
