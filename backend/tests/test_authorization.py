"""Authorisation is enforced by the API regardless of what the UI shows."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import OTHER_TENANT, auth_headers
from tests.helpers import create_project, find_resource, seeded

PROJECT = {"name": "X", "slug": "x"}


@pytest.mark.parametrize(
    ("role", "method", "path", "body", "allowed"),
    [
        ("viewer", "POST", "/api/v1/projects", PROJECT, False),
        ("operator", "POST", "/api/v1/projects", PROJECT, False),
        ("admin", "POST", "/api/v1/projects", PROJECT, True),
        ("viewer", "GET", "/api/v1/azure/identity", None, False),
        ("admin", "GET", "/api/v1/azure/identity", None, True),
        ("viewer", "GET", "/api/v1/users", None, False),
        ("admin", "GET", "/api/v1/users", None, False),
        ("super_admin", "GET", "/api/v1/users", None, True),
        ("viewer", "GET", "/api/v1/audit-logs", None, False),
        ("admin", "GET", "/api/v1/audit-logs", None, True),
        ("viewer", "GET", "/api/v1/logs/targets", None, False),
        ("operator", "GET", "/api/v1/logs/targets", None, True),
        ("viewer", "POST", "/api/v1/azure/sync", None, False),
        ("operator", "POST", "/api/v1/azure/sync", None, True),
        ("operator", "GET", "/api/v1/notification-channels", None, False),
        ("admin", "GET", "/api/v1/notification-channels", None, True),
        ("viewer", "GET", "/api/v1/overview", None, True),
    ],
)
async def test_role_matrix(
    client: httpx.AsyncClient, role: str, method: str, path: str, body: dict | None, allowed: bool
) -> None:
    response = await client.request(method, path, json=body, headers=auth_headers(role))
    if allowed:
        assert response.status_code < 400, response.text
    else:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_denials_are_audited(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/projects", json=PROJECT, headers=auth_headers("viewer"))
    logs = (await client.get("/api/v1/audit-logs", params={"result": "denied"}, headers=auth_headers("admin"))).json()[
        "items"
    ]
    assert any(e["action"] == "authorization.denied" and e["details"]["path"] == "/api/v1/projects" for e in logs)


async def test_organisation_isolation(client: httpx.AsyncClient) -> None:
    await seeded(client)
    resource = await find_resource(client, "app-crm-prod-uks")
    other = auth_headers("super_admin", tenant=OTHER_TENANT)
    assert (await client.get(f"/api/v1/resources/{resource['id']}", headers=other)).status_code == 404
    assert (await client.get("/api/v1/resources", headers=other)).json()["total"] == 0
    assert (await client.get("/api/v1/projects", headers=other)).json() == []
    metrics = await client.get(
        f"/api/v1/resources/{resource['id']}/metrics", params={"metrics": "requests"}, headers=other
    )
    assert metrics.status_code == 404


async def test_role_changes_cannot_escalate(client: httpx.AsyncClient) -> None:
    await client.get("/api/v1/auth/me", headers=auth_headers("super_admin"))
    # A user without Entra app roles, so their role is managed in-app.
    from tests.conftest import add_member, make_token

    await add_member("plain-user", role="viewer")
    viewer_token = make_token("plain-user")
    await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {viewer_token}"})
    users = (await client.get("/api/v1/users", headers=auth_headers("super_admin"))).json()["items"]
    plain = next(u for u in users if u["role_key"] == "viewer" and not u["role_managed_by_entra"])
    me = next(u for u in users if u["role_key"] == "super_admin")

    ok = await client.patch(
        f"/api/v1/users/{plain['id']}", json={"role_key": "admin"}, headers=auth_headers("super_admin")
    )
    assert ok.status_code == 200 and ok.json()["role_key"] == "admin"

    own = await client.patch(
        f"/api/v1/users/{me['id']}", json={"role_key": "viewer"}, headers=auth_headers("super_admin")
    )
    assert own.status_code == 422

    managed = (
        next(u for u in users if u["role_managed_by_entra"] and u["id"] != me["id"])
        if any(u["role_managed_by_entra"] and u["id"] != me["id"] for u in users)
        else None
    )
    if managed:
        r = await client.patch(
            f"/api/v1/users/{managed['id']}", json={"role_key": "viewer"}, headers=auth_headers("super_admin")
        )
        assert r.status_code == 422


async def test_frontend_cannot_bypass_via_other_projects(client: httpx.AsyncClient) -> None:
    project = await create_project(client, "crm")
    other = auth_headers("super_admin", tenant=OTHER_TENANT)
    response = await client.patch(f"/api/v1/projects/{project['id']}", json={"name": "hijack"}, headers=other)
    assert response.status_code == 404
