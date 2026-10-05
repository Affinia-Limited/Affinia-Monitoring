"""Authentication: Entra token validation is enforced on every protected endpoint."""

from __future__ import annotations

import httpx
import jwt
import pytest

from tests.conftest import (
    AUDIENCE,
    OTHER_SIGNING_KEY,
    OTHER_TENANT,
    TEST_TENANT,
    add_member,
    auth_headers,
    make_token,
    member_oid,
)


async def _me(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


async def test_approved_member_role_follows_entra_app_role(client: httpx.AsyncClient) -> None:
    await add_member("oid-1", role="viewer")
    response = await _me(client, make_token("oid-1", roles=["Monitoring.Operator"], email="op@example.test"))
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "operator"
    assert body["role_managed_by_entra"] is True
    assert "logs:run_kql" in body["permissions"]
    assert "azure:connect" not in body["permissions"]


async def test_member_without_app_roles_keeps_assigned_role(client: httpx.AsyncClient) -> None:
    await add_member("oid-2", role="operator")
    response = await _me(client, make_token("oid-2"))
    assert response.status_code == 200
    assert response.json()["role"] == "operator"
    assert response.json()["role_managed_by_entra"] is False


async def test_missing_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.json()["error"]["request_id"]


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"exp_offset": -3600}, 401, "TOKEN_EXPIRED"),
        ({"aud": "api://someone-else"}, 401, "UNAUTHENTICATED"),
        ({"iss": "https://evil.example/v2.0"}, 401, "UNAUTHENTICATED"),
        ({"key": OTHER_SIGNING_KEY}, 401, "UNAUTHENTICATED"),
        ({"kid": "unknown-kid"}, 401, "UNAUTHENTICATED"),
        ({"tenant": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"}, 401, "UNAUTHENTICATED"),
        ({"scp": None}, 403, "PERMISSION_DENIED"),
        ({"scp": "some.other.scope"}, 403, "PERMISSION_DENIED"),
    ],
)
async def test_invalid_tokens_are_rejected(client: httpx.AsyncClient, kwargs: dict, status: int, code: str) -> None:
    response = await _me(client, make_token("oid-x", **kwargs))
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


async def test_symmetric_and_unsigned_tokens_are_rejected(client: httpx.AsyncClient) -> None:
    hs = jwt.encode(
        {"oid": "x", "tid": TEST_TENANT, "aud": AUDIENCE, "scp": "access_as_user"},
        "secret",
        algorithm="HS256",
        headers={"kid": "test-kid"},
    )
    assert (await _me(client, hs)).status_code == 401
    unsigned = jwt.encode({"oid": "x", "tid": TEST_TENANT, "aud": AUDIENCE}, None, algorithm="none")
    assert (await _me(client, unsigned)).status_code == 401
    assert (await _me(client, "not-a-jwt")).status_code == 401


async def test_non_bearer_scheme_rejected(client: httpx.AsyncClient) -> None:
    token = make_token("oid-3")
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Basic {token}"})
    assert response.status_code == 401


async def test_allowed_second_tenant_gets_separate_organisation(client: httpx.AsyncClient) -> None:
    a = (await client.get("/api/v1/auth/me", headers=auth_headers("admin"))).json()
    b = (await client.get("/api/v1/auth/me", headers=auth_headers("admin", tenant=OTHER_TENANT))).json()
    assert a["organization_id"] != b["organization_id"]


async def test_entra_role_removal_downgrades_to_viewer(client: httpx.AsyncClient) -> None:
    await add_member("oid-4", role="viewer")
    assert (await _me(client, make_token("oid-4", roles=["Monitoring.Admin"]))).json()["role"] == "admin"
    assert (await _me(client, make_token("oid-4"))).json()["role"] == "viewer"


async def test_login_is_audited_without_tokens(client: httpx.AsyncClient) -> None:
    token = make_token(member_oid("super_admin"), roles=["Monitoring.SuperAdmin"])
    session = await client.post("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert session.status_code == 200
    logs = (await client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {token}"})).json()["items"]
    logins = [e for e in logs if e["action"] == "user.login_allowed"]
    assert [e["details"]["trigger"] for e in logins] == ["interactive_sign_in"]
    assert logins[0]["ip_address"]
    assert token not in str(logs)
    assert "eyJ" not in str(logs)


async def test_public_auth_config_contains_no_secrets(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/auth/config")).json()
    assert body["auth_mode"] == "entra"
    assert set(body) == {"auth_mode", "tenant_id", "client_id", "api_scope", "authority"}
