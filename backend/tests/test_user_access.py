"""Admin-controlled access: Entra authentication alone never grants access to the platform."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.api.v1 import (
    alerts,
    auth,
    azure_connections,
    dashboards,
    logs,
    overview,
    projects,
    resources,
    search,
    users,
)
from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.models import AuditLog, User
from tests.conftest import (
    OTHER_TENANT,
    TEST_TENANT,
    add_member,
    auth_headers,
    bearer,
    make_token,
    member_oid,
)

NOT_GRANTED = "ACCESS_NOT_GRANTED"
SA = auth_headers("super_admin")


def _token(oid: str, email: str = "user@example.test", **kwargs: Any) -> dict[str, str]:
    return bearer(make_token(oid, email=email, **kwargs))


async def _audit(action: str) -> list[AuditLog]:
    async with get_sessionmaker()() as session:
        return list(await session.scalars(select(AuditLog).where(AuditLog.action == action)))


async def _user(user_id: uuid.UUID | str) -> User:
    async with get_sessionmaker()() as session:
        user = await session.get(User, uuid.UUID(str(user_id)))
        assert user is not None
        return user


async def _invite(client: httpx.AsyncClient, email: str, role: str = "viewer", **extra: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/users/invite", json={"email": email, "role_key": role, **extra}, headers=SA)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------- sign-in decisions


async def test_active_member_is_granted_access(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers=auth_headers("viewer"))
    assert response.status_code == 200
    assert response.json()["role"] == "viewer"


async def test_valid_entra_user_not_in_database_is_denied(client: httpx.AsyncClient) -> None:
    headers = _token(str(uuid.uuid4()), "employee@example.test")
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == NOT_GRANTED
    assert "details" not in error
    # Nothing is created for an unknown identity.
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(User).where(User.email == "employee@example.test")) is None
    denied = await _audit("user.login_denied")
    assert [e.details["reason"] for e in denied] == ["USER_NOT_FOUND"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/v1/projects", {"name": "X", "slug": "x"}),
        ("GET", "/api/v1/projects", None),
        ("GET", "/api/v1/resources", None),
        ("GET", "/api/v1/dashboards", None),
        ("GET", "/api/v1/alerts", None),
        ("GET", "/api/v1/logs/targets", None),
        ("GET", "/api/v1/azure/connections", None),
        ("POST", "/api/v1/azure/sync", None),
        ("GET", "/api/v1/users", None),
    ],
)
async def test_unapproved_user_cannot_call_protected_apis_directly(
    client: httpx.AsyncClient, method: str, path: str, body: dict | None
) -> None:
    # Even with the Super Admin app role in the token: app roles never grant membership.
    headers = _token(str(uuid.uuid4()), roles=["Monitoring.SuperAdmin"])
    response = await client.request(method, path, json=body, headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == NOT_GRANTED


def _all_protected_routes() -> list[tuple[str, str]]:
    routes = []
    for module in (auth, overview, projects, azure_connections, resources, dashboards, logs, alerts, search, users):
        for route in module.router.routes:
            if route.path == "/auth/config":
                continue
            for method in sorted(route.methods):
                routes.append((method, "/api/v1" + route.path))
    return routes


@pytest.mark.parametrize(("method", "path"), _all_protected_routes())
async def test_every_protected_route_enforces_membership(client: httpx.AsyncClient, method: str, path: str) -> None:
    concrete = path
    while "{" in concrete:
        start, end = concrete.index("{"), concrete.index("}")
        concrete = concrete[:start] + str(uuid.uuid4()) + concrete[end + 1 :]
    response = await client.request(method, concrete, json={}, headers=_token(str(uuid.uuid4())))
    assert response.status_code == 403, f"{method} {path}: {response.status_code} {response.text}"
    assert response.json()["error"]["code"] == NOT_GRANTED


async def test_pending_invitation_is_activated_on_first_sign_in(client: httpx.AsyncClient) -> None:
    invited = await _invite(client, "John.Smith@Example.test", "operator", display_name="John Smith")
    assert invited["status"] == "pending"
    assert invited["email"] == "john.smith@example.test"
    assert invited["entra_object_id"] is None

    oid = str(uuid.uuid4())
    # Case-insensitive email match within the same organisation and tenant.
    response = await client.get("/api/v1/auth/me", headers=_token(oid, "john.smith@EXAMPLE.test", name="John Smith"))
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "operator"

    user = await _user(invited["id"])
    assert user.status == "active"
    assert user.entra_object_id == oid
    assert user.activated_at is not None
    assert user.invitation_expires_at is None
    assert len(await _audit("user.activated")) == 1


async def test_after_activation_access_is_bound_to_object_id_not_email(client: httpx.AsyncClient) -> None:
    invited = await _invite(client, "sarah@example.test")
    first = str(uuid.uuid4())
    assert (await client.get("/api/v1/auth/me", headers=_token(first, "sarah@example.test"))).status_code == 200

    # A different Entra identity presenting the same email (recycled or renamed UPN) is refused.
    other = await client.get("/api/v1/auth/me", headers=_token(str(uuid.uuid4()), "sarah@example.test"))
    assert other.status_code == 403
    assert other.json()["error"]["code"] == NOT_GRANTED
    assert [e.details["reason"] for e in await _audit("user.login_denied")] == ["IDENTITY_MISMATCH"]

    # The bound identity keeps working after its email changes in Entra.
    renamed = await client.get("/api/v1/auth/me", headers=_token(first, "sarah.jones@example.test"))
    assert renamed.status_code == 200
    assert (await _user(invited["id"])).email == "sarah.jones@example.test"


async def test_invitation_cannot_be_redeemed_from_another_tenant(client: httpx.AsyncClient) -> None:
    invited = await _invite(client, "john@example.test")
    response = await client.get(
        "/api/v1/auth/me", headers=_token(str(uuid.uuid4()), "john@example.test", tenant=OTHER_TENANT)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == NOT_GRANTED
    assert (await _user(invited["id"])).status == "pending"


async def test_expired_invitation_is_refused(client: httpx.AsyncClient) -> None:
    await add_member(
        None,
        status="pending",
        email="late@example.test",
        invitation_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    response = await client.get("/api/v1/auth/me", headers=_token(str(uuid.uuid4()), "late@example.test"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == NOT_GRANTED
    assert [e.details["reason"] for e in await _audit("user.login_denied")] == ["INVITATION_EXPIRED"]


async def test_suspended_member_is_denied_with_suspension_message(client: httpx.AsyncClient) -> None:
    await add_member("suspended-oid", status="suspended")
    response = await client.get("/api/v1/auth/me", headers=_token("suspended-oid"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCESS_SUSPENDED"
    assert "suspended" in response.json()["error"]["message"]


async def test_deactivated_member_is_denied(client: httpx.AsyncClient) -> None:
    await add_member("gone-oid", status="deactivated")
    response = await client.get("/api/v1/projects", headers=_token("gone-oid"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == NOT_GRANTED
    assert [e.details["reason"] for e in await _audit("user.access_denied")] == ["USER_DEACTIVATED"]


async def test_denial_responses_do_not_reveal_why(client: httpx.AsyncClient) -> None:
    await add_member("deact", status="deactivated", email="d@example.test")
    await add_member(
        None, status="pending", email="x@example.test", invitation_expires_at=datetime.now(UTC) - timedelta(days=1)
    )
    bodies = []
    for headers in (
        _token(str(uuid.uuid4()), "nobody@example.test"),
        _token("deact", "d@example.test"),
        _token(str(uuid.uuid4()), "x@example.test"),
    ):
        response = await client.get("/api/v1/auth/me", headers=headers)
        error = response.json()["error"]
        bodies.append((response.status_code, error["code"], error["message"], error.get("details")))
    assert len(set(bodies)) == 1


async def test_denials_are_audited_once_per_window(client: httpx.AsyncClient) -> None:
    headers = _token(str(uuid.uuid4()), "probe@example.test")
    for _ in range(5):
        await client.get("/api/v1/resources", headers=headers)
    entries = await _audit("user.access_denied")
    assert len(entries) == 1
    assert entries[0].organization_id is not None
    assert "eyJ" not in str(entries[0].details)


async def test_untrusted_tenant_is_rejected_before_any_lookup(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers=_token("x", tenant="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"))
    assert response.status_code == 401


async def test_repeated_failures_are_rate_limited(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_auth_failures_per_minute", 3)
    # An identity without access is budgeted per identity.
    stranger = _token(str(uuid.uuid4()))
    statuses = [(await client.get("/api/v1/auth/me", headers=stranger)).status_code for _ in range(5)]
    assert statuses[:3] == [403, 403, 403]
    assert statuses[3:] == [429, 429]
    # Invalid tokens are budgeted per client IP.
    garbage = {"Authorization": "Bearer not-a-token"}
    statuses = [(await client.get("/api/v1/auth/me", headers=garbage)).status_code for _ in range(5)]
    assert statuses[:3] == [401, 401, 401]
    assert statuses[3:] == [429, 429]


async def test_failed_attempts_never_lock_out_valid_users(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anonymous junk from the same (proxy) IP must not deny service to signed-in members."""
    monkeypatch.setattr(get_settings(), "rate_limit_auth_failures_per_minute", 3)
    for _ in range(10):
        await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"})
    for _ in range(5):
        await client.get("/api/v1/auth/me", headers=_token(str(uuid.uuid4())))
    assert (await client.get("/api/v1/projects", headers=auth_headers("viewer"))).status_code == 200


# ---------------------------------------------------------------- immediate effect of admin actions


async def test_suspension_takes_effect_on_the_next_request(client: httpx.AsyncClient) -> None:
    user_id = await add_member("john-oid", role="viewer")
    headers = _token("john-oid")
    assert (await client.get("/api/v1/projects", headers=headers)).status_code == 200

    assert (await client.post(f"/api/v1/users/{user_id}/suspend", headers=SA)).json()["status"] == "suspended"
    blocked = await client.get("/api/v1/projects", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "ACCESS_SUSPENDED"

    assert (await client.post(f"/api/v1/users/{user_id}/reactivate", headers=SA)).json()["status"] == "active"
    assert (await client.get("/api/v1/projects", headers=headers)).status_code == 200

    assert (await client.post(f"/api/v1/users/{user_id}/deactivate", headers=SA)).json()["status"] == "deactivated"
    assert (await client.get("/api/v1/projects", headers=headers)).json()["error"]["code"] == NOT_GRANTED
    actions = {e.action for e in await _audit("user.suspended")} | {e.action for e in await _audit("user.reactivated")}
    assert actions == {"user.suspended", "user.reactivated"}
    deactivated = await _user(user_id)
    assert deactivated.deactivated_at is not None  # the row is kept


# ---------------------------------------------------------------- user management permissions


@pytest.mark.parametrize(
    ("role", "allowed"), [("viewer", False), ("operator", False), ("admin", False), ("super_admin", True)]
)
async def test_only_user_managers_can_manage_users(client: httpx.AsyncClient, role: str, allowed: bool) -> None:
    headers = auth_headers(role)
    target = await add_member("target", role="viewer")
    calls = [
        await client.get("/api/v1/users", headers=headers),
        await client.get(f"/api/v1/users/{target}", headers=headers),
        await client.post("/api/v1/users/invite", json={"email": f"{role}-new@example.test"}, headers=headers),
        await client.patch(f"/api/v1/users/{target}", json={"role_key": "operator"}, headers=headers),
        await client.post(f"/api/v1/users/{target}/suspend", headers=headers),
        await client.get(f"/api/v1/users/{target}/audit", headers=headers),
    ]
    for response in calls:
        if allowed:
            assert response.status_code < 400, response.text
        else:
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_cannot_modify_self(client: httpx.AsyncClient) -> None:
    me = (await client.get("/api/v1/auth/me", headers=SA)).json()
    for call in (
        client.post(f"/api/v1/users/{me['id']}/deactivate", headers=SA),
        client.post(f"/api/v1/users/{me['id']}/suspend", headers=SA),
    ):
        response = await call
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "SELF_MODIFICATION"


async def test_last_super_admin_is_protected(client: httpx.AsyncClient) -> None:
    from app.api.deps import CurrentUser
    from app.core.errors import ConflictError
    from app.core.permissions import Role, permissions_for
    from app.services import user_management

    seeded = (await client.get("/api/v1/auth/me", headers=SA)).json()
    # With two Super Admins, one may demote and deactivate the other.
    second_id = await add_member("sa-2", role="super_admin")
    demote = await client.patch(f"/api/v1/users/{second_id}", json={"role_key": "admin"}, headers=SA)
    assert demote.status_code == 200 and demote.json()["role_key"] == "admin"
    await client.patch(f"/api/v1/users/{second_id}", json={"role_key": "super_admin"}, headers=SA)
    assert (await client.post(f"/api/v1/users/{second_id}/deactivate", headers=SA)).status_code == 200

    # Only one active Super Admin remains: it cannot be demoted, suspended or deactivated, even by an
    # actor that holds Super Admin outside the database (for example through an Entra app role).
    actor = CurrentUser(
        id=uuid.uuid4(),
        organization_id=uuid.UUID(seeded["organization_id"]),
        email=None,
        display_name=None,
        role=Role.super_admin,
        permissions=permissions_for(Role.super_admin),
        role_managed_by_entra=True,
    )
    from starlette.requests import Request

    request = Request({"type": "http", "headers": [], "path": "/", "method": "POST"})
    async with get_sessionmaker()() as session:
        target = await session.get(User, uuid.UUID(seeded["id"]))
        assert target is not None
        target.role_managed_by_entra = False
        for attempt in (
            user_management.change_role(session, actor, target, Role.admin, request),
            user_management.change_status(session, actor, target, "suspend", request),
            user_management.change_status(session, actor, target, "deactivate", request),
        ):
            with pytest.raises(ConflictError) as exc:
                await attempt
            assert exc.value.code == "LAST_SUPER_ADMIN"


async def test_admin_cannot_grant_super_admin(client: httpx.AsyncClient) -> None:
    from starlette.requests import Request

    from app.api.deps import CurrentUser
    from app.core.errors import PermissionDeniedError
    from app.core.permissions import Permission, Role, permissions_for
    from app.services import user_management

    admin_id = await add_member("adm", role="admin")
    target_id = await add_member("tgt", role="viewer")
    admin = await _user(admin_id)
    # Even if an Admin were given users:manage, the rank rules still stop escalation.
    actor = CurrentUser(
        id=admin_id,
        organization_id=admin.organization_id,
        email=None,
        display_name=None,
        role=Role.admin,
        permissions=permissions_for(Role.admin) | {Permission.manage_users},
        role_managed_by_entra=False,
    )
    request = Request({"type": "http", "headers": [], "path": "/", "method": "POST"})
    async with get_sessionmaker()() as session:
        target = await session.get(User, target_id)
        own = await session.get(User, admin_id)
        assert target is not None and own is not None
        with pytest.raises(PermissionDeniedError):
            await user_management.change_role(session, actor, target, Role.super_admin, request)
        with pytest.raises(PermissionDeniedError):
            await user_management.invite(
                session, actor, email="boss@example.test", role=Role.super_admin, display_name=None, request=request
            )
        from app.core.errors import ValidationFailedError

        with pytest.raises(ValidationFailedError):
            await user_management.change_role(session, actor, own, Role.super_admin, request)


# ---------------------------------------------------------------- invitations and listing


async def test_invitation_rules(client: httpx.AsyncClient) -> None:
    first = await _invite(client, "dup@example.test")
    # Re-inviting a pending email refreshes the same invitation instead of creating a second one.
    again = await _invite(client, "DUP@example.test", "operator")
    assert again["id"] == first["id"] and again["role_key"] == "operator"

    await add_member("active-oid", email="taken@example.test")
    conflict = await client.post("/api/v1/users/invite", json={"email": "taken@example.test"}, headers=SA)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "USER_EXISTS"

    bad = await client.post("/api/v1/users/invite", json={"email": "not-an-email"}, headers=SA)
    assert bad.status_code == 422

    # Revoking an unredeemed invitation, then reactivating it, re-opens the invitation.
    revoked = await client.post(f"/api/v1/users/{first['id']}/deactivate", headers=SA)
    assert revoked.json()["status"] == "deactivated"
    denied = await client.get("/api/v1/auth/me", headers=_token(str(uuid.uuid4()), "dup@example.test"))
    assert denied.status_code == 403
    reopened = await client.post(f"/api/v1/users/{first['id']}/reactivate", headers=SA)
    assert reopened.json()["status"] == "pending"
    assert (
        await client.get("/api/v1/auth/me", headers=_token(str(uuid.uuid4()), "dup@example.test"))
    ).status_code == 200


async def test_user_list_search_filter_and_paging(client: httpx.AsyncClient) -> None:
    await _invite(client, "alice@example.test", "operator", display_name="Alice Example")
    await _invite(client, "bob@example.test", display_name="Bob 100%_match")
    await add_member("susp", status="suspended", email="carol@example.test", display_name="Carol")

    def names(body: dict[str, Any]) -> set[str]:
        return {u["display_name"] for u in body["items"]}

    assert names((await client.get("/api/v1/users", params={"q": "alice"}, headers=SA)).json()) == {"Alice Example"}
    assert names((await client.get("/api/v1/users", params={"q": "100%_"}, headers=SA)).json()) == {"Bob 100%_match"}
    assert names((await client.get("/api/v1/users", params={"q": "%"}, headers=SA)).json()) == {"Bob 100%_match"}
    assert names((await client.get("/api/v1/users", params={"status": "suspended"}, headers=SA)).json()) == {"Carol"}
    operators = (await client.get("/api/v1/users", params={"role": "operator", "status": "pending"}, headers=SA)).json()
    assert names(operators) == {"Alice Example"}
    assert operators["items"][0]["created_by_name"] == "Test User"

    page = (await client.get("/api/v1/users", params={"page_size": 2}, headers=SA)).json()
    assert len(page["items"]) == 2 and page["total"] == 7  # 4 seeded + 3 added
    listed = page["items"][0]
    assert "entra_object_id" not in listed


async def test_user_detail_and_audit_history(client: httpx.AsyncClient) -> None:
    invited = await _invite(client, "dee@example.test")
    detail = (await client.get(f"/api/v1/users/{invited['id']}", headers=SA)).json()
    assert detail["entra_tenant_id"] == TEST_TENANT
    assert detail["invited_at"] and detail["invitation_expires_at"]
    history = (await client.get(f"/api/v1/users/{invited['id']}/audit", headers=SA)).json()
    assert [e["action"] for e in history["items"]] == ["user.invited"]


async def test_users_are_isolated_per_organisation(client: httpx.AsyncClient) -> None:
    target = await add_member("iso", email="iso@example.test")
    other = auth_headers("super_admin", tenant=OTHER_TENANT)
    assert (await client.get(f"/api/v1/users/{target}", headers=other)).status_code == 404
    assert (await client.post(f"/api/v1/users/{target}/suspend", headers=other)).status_code == 404
    listed = (await client.get("/api/v1/users", params={"q": "iso@"}, headers=other)).json()
    assert listed["total"] == 0


# ---------------------------------------------------------------- bootstrap


async def _suspend_seeded_super_admin() -> None:
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.entra_object_id == member_oid("super_admin")))
        assert user is not None
        user.status = "suspended"
        await session.commit()


async def test_bootstrap_provisions_first_super_admin_only_once(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    monkeypatch.setattr(get_settings(), "bootstrap_super_admin_oids", [first, f"{TEST_TENANT}/{second}"])
    await _suspend_seeded_super_admin()  # the organisation now has no active Super Admin

    response = await client.get("/api/v1/auth/me", headers=_token(first, "aditya@example.test"))
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "super_admin"
    assert len(await _audit("user.bootstrapped")) == 1

    # An active Super Admin now exists, so the remaining bootstrap entry is ignored.
    late = await client.get("/api/v1/auth/me", headers=_token(second))
    assert late.status_code == 403 and late.json()["error"]["code"] == NOT_GRANTED


async def test_bootstrap_is_ignored_when_a_super_admin_exists(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    oid = str(uuid.uuid4())
    monkeypatch.setattr(get_settings(), "bootstrap_super_admin_oids", [oid])
    response = await client.get("/api/v1/auth/me", headers=_token(oid))
    assert response.status_code == 403


async def test_bootstrap_requires_the_configured_tenant(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    oid = str(uuid.uuid4())
    monkeypatch.setattr(get_settings(), "bootstrap_super_admin_oids", [f"{TEST_TENANT}/{oid}"])
    await _suspend_seeded_super_admin()
    # Same object id presented from another (allowed) tenant: not the configured identity.
    response = await client.get("/api/v1/auth/me", headers=_token(oid, tenant=OTHER_TENANT))
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"BOOTSTRAP_SUPER_ADMIN_OIDS": "not-a-guid"}, "BOOTSTRAP_SUPER_ADMIN_OIDS"),
        (
            {"BOOTSTRAP_SUPER_ADMIN_OIDS": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/11111111-1111-4111-8111-111111111111"},
            "not allowed",
        ),
        (
            {"ENVIRONMENT": "production", "AUTH_MODE": "dev", "AZURE_PROVIDER": "azure", "TASK_BACKEND": "celery"},
            "AUTH_MODE=dev",
        ),
    ],
)
def test_insecure_configuration_is_refused(monkeypatch: pytest.MonkeyPatch, env: dict[str, str], message: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=message):
        Settings()
