from __future__ import annotations

from typing import Any

import httpx

from app.services.azure.mock.estate import MOCK_SUBSCRIPTIONS, MOCK_TENANT_ID
from app.services.jobs import wait_for_inline_jobs
from tests.conftest import auth_headers

SUB_A = MOCK_SUBSCRIPTIONS[0].subscription_id
SUB_B = MOCK_SUBSCRIPTIONS[1].subscription_id


async def create_project(
    client: httpx.AsyncClient,
    slug: str = "crm",
    name: str | None = None,
    envs: tuple[str, ...] = ("dev", "uat", "prod"),
    role: str = "admin",
) -> dict[str, Any]:
    kinds = {"dev": ("Development", "development"), "uat": ("UAT", "uat"), "prod": ("Production", "production")}
    body = {
        "name": name or slug.upper(),
        "slug": slug,
        "environments": [{"name": kinds[e][0], "slug": e, "kind": kinds[e][1]} for e in envs],
    }
    response = await client.post("/api/v1/projects", json=body, headers=auth_headers(role))
    assert response.status_code == 201, response.text
    return response.json()


async def connect(
    client: httpx.AsyncClient, subscriptions: list[str] | None = None, role: str = "admin", **extra: Any
) -> dict[str, Any]:
    body = {"name": "Demo", "tenant_id": MOCK_TENANT_ID, "subscription_ids": subscriptions or [SUB_A], **extra}
    response = await client.post("/api/v1/azure/connections", json=body, headers=auth_headers(role))
    assert response.status_code == 202, response.text
    await wait_for_inline_jobs()
    return response.json()


async def seeded(client: httpx.AsyncClient) -> dict[str, Any]:
    """CRM + PRISM projects and a synced connection to mock subscription A."""
    crm = await create_project(client, "crm")
    prism = await create_project(client, "prism", envs=("dev", "prod"))
    created = await connect(client)
    return {"crm": crm, "prism": prism, "connection": created["connection"], "run": created["sync_run"]}


async def find_resource(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    response = await client.get("/api/v1/resources", params={"q": name}, headers=auth_headers("viewer"))
    assert response.status_code == 200, response.text
    items = [r for r in response.json()["items"] if r["name"] == name]
    assert items, f"resource {name} not found"
    return items[0]
