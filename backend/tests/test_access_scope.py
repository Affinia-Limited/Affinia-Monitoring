"""Scoped access: members see and act only inside their projects / environments / resources.

The estate: CRM (dev, uat, prod) and PRISM (dev, prod) from the mock subscription, with alerts on
both. Members:

* crm_viewer   viewer,   CRM (whole project)
* crm_prod_op  operator, CRM / Production
* prism_admin  admin,    PRISM (whole project)
* two_res      viewer,   two CRM Production resources
* nobody       viewer,   no grants
* the seeded admin / viewer have "all projects"; super_admin is unrestricted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db.session import session_scope
from app.models import User
from app.services.alerts.evaluator import evaluate_alert_rules
from app.services.azure.provider import get_azure_services
from tests.conftest import add_member, auth_headers, member_oid
from tests.helpers import find_resource, seeded

SA = auth_headers("super_admin")


@dataclass
class World:
    crm: dict[str, Any]
    prism: dict[str, Any]
    crm_prod: dict[str, Any]
    crm_dev: dict[str, Any]
    prism_prod: dict[str, Any]
    crm_app: dict[str, Any]
    crm_plan: dict[str, Any]
    crm_dev_app: dict[str, Any]
    prism_app: dict[str, Any]
    members: dict[str, dict[str, Any]]

    def h(self, name: str) -> dict[str, str]:
        m = self.members[name]
        return auth_headers(m["role"], oid=m["oid"])

    def id(self, name: str) -> str:
        return str(self.members[name]["id"])


async def _member(client: httpx.AsyncClient, name: str, role: str, grants: list[dict[str, Any]]) -> dict[str, Any]:
    oid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"scope/{name}"))
    user_id = await add_member(oid, role=role, email=f"{name}@example.test", all_projects=False)
    if grants:
        r = await client.put(f"/api/v1/users/{user_id}/access", json={"grants": grants}, headers=SA)
        assert r.status_code == 200, r.text
    return {"oid": oid, "role": role, "id": user_id}


@pytest.fixture
async def world(client: httpx.AsyncClient) -> World:
    data = await seeded(client)
    crm, prism = data["crm"], data["prism"]

    def env(project: dict[str, Any], slug: str) -> dict[str, Any]:
        return next(e for e in project["environments"] if e["slug"] == slug)

    crm_app = await find_resource(client, "app-crm-prod-uks")
    crm_plan = await find_resource(client, "asp-crm-prod-uks")
    crm_dev_app = await find_resource(client, "app-crm-dev-uks")
    prism_app = await find_resource(client, "app-prism-prod-uks")

    # Alerts on both projects: an organisation-wide custom rule that fires on every App Service,
    # a PRISM-only rule, and template coverage for the whole organisation.
    rule = {
        "name": "Any app CPU",
        "monitor_key": "app_service",
        "metric_name": "plan_cpu",
        "aggregation": "Average",
        "operator": "gt",
        "threshold": 1,
        "severity": "critical",
        "window_minutes": 15,
    }
    assert (await client.post("/api/v1/alert-rules", json=rule, headers=SA)).status_code == 201
    prism_rule = {**rule, "name": "PRISM CPU", "project_id": prism["id"]}
    assert (await client.post("/api/v1/alert-rules", json=prism_rule, headers=SA)).status_code == 201
    assert (await client.post("/api/v1/alert-template-assignments", json={}, headers=SA)).status_code == 201
    me = (await client.get("/api/v1/auth/me", headers=SA)).json()
    async with session_scope() as db:
        await evaluate_alert_rules(db, get_azure_services(), uuid.UUID(me["organization_id"]), force=True)

    crm_prod, prism_prod = env(crm, "prod"), env(prism, "prod")
    members = {
        "crm_viewer": await _member(client, "crm_viewer", "viewer", [{"project_id": crm["id"]}]),
        "crm_prod_op": await _member(
            client, "crm_prod_op", "operator", [{"project_id": crm["id"], "environment_id": crm_prod["id"]}]
        ),
        "prism_admin": await _member(client, "prism_admin", "admin", [{"project_id": prism["id"]}]),
        "two_res": await _member(
            client,
            "two_res",
            "viewer",
            [
                {"project_id": crm["id"], "environment_id": crm_prod["id"], "resource_id": crm_app["id"]},
                {"project_id": crm["id"], "environment_id": crm_prod["id"], "resource_id": crm_plan["id"]},
            ],
        ),
        "nobody": await _member(client, "nobody", "viewer", []),
    }
    return World(crm, prism, crm_prod, env(crm, "dev"), prism_prod, crm_app, crm_plan, crm_dev_app, prism_app, members)


async def _all(client: httpx.AsyncClient, path: str, headers: dict[str, str], **params: Any) -> Any:
    r = await client.get(path, params=params, headers=headers)
    assert r.status_code == 200, f"{path}: {r.text}"
    return r.json()


# ---------------------------------------------------------------- reading


async def test_project_member_sees_only_their_project_everywhere(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("crm_viewer")
    crm, prism = world.crm["id"], world.prism["id"]

    assert [p["id"] for p in await _all(client, "/api/v1/projects", h)] == [crm]
    assert (await client.get(f"/api/v1/projects/{prism}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{prism}/comparison", headers=h)).status_code == 404

    resources = (await _all(client, "/api/v1/resources", h, page_size=500))["items"]
    assert resources and {r["project_id"] for r in resources} == {crm}
    facets = await _all(client, "/api/v1/resources/facets", h)
    assert sum(f["count"] for f in facets["health"]) == len(resources)
    assert (await _all(client, "/api/v1/resources", h, project_id=prism))["total"] == 0

    for path in (
        "",
        "/metric-definitions",
        "/activity",
        "/related/children",
        "/alert-plan",
        "/metrics?metrics=plan_cpu",
    ):
        r = await client.get(f"/api/v1/resources/{world.prism_app['id']}{path}", headers=h)
        assert r.status_code == 404, f"{path}: {r.status_code}"
    assert (await client.get(f"/api/v1/dashboards/by-resource/{world.prism_app['id']}", headers=h)).status_code == 404

    overview = await _all(client, "/api/v1/overview", h)
    assert [p["id"] for p in overview["project_health"]] == [crm]
    assert overview["totals"]["projects"] == 1
    assert all(a["project_id"] == crm for a in overview["recent_alerts"])
    assert all(n["project_name"] == "CRM" for n in overview["needs_attention"])
    assert overview["feed_errors"] == []

    live = await _all(client, "/api/v1/live/resources", h, ids=f"{world.prism_app['id']},{world.crm_app['id']}")
    assert list(live["resources"]) == [world.crm_app["id"]]

    dashboards = await _all(client, "/api/v1/dashboards", h)
    assert dashboards and {d["project_name"] for d in dashboards} == {"CRM"}

    alerts = (await _all(client, "/api/v1/alerts", h, page_size=200))["items"]
    assert alerts and {a["project_id"] for a in alerts} == {crm}
    everyone = (await _all(client, "/api/v1/alerts", SA, page_size=200))["items"]
    prism_alert = next(a for a in everyone if a["project_id"] == prism)
    assert (await client.get(f"/api/v1/alerts/{prism_alert['id']}", headers=h)).status_code == 404

    rules = await _all(client, "/api/v1/alert-rules", h)
    assert rules == []  # one rule is organisation-wide, the other is PRISM's

    templates = await _all(client, "/api/v1/alert-templates", h)
    app_service = next(t for t in templates if t["monitor_key"] == "app_service")
    crm_apps = [r for r in resources if r["monitor_key"] == "app_service"]
    assert app_service["resource_count"] == len(crm_apps)
    assert await _all(client, "/api/v1/alert-template-assignments", h) == []  # organisation-wide coverage


async def test_search_and_logs_are_scoped(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("crm_viewer")
    hits = (await _all(client, "/api/v1/search", h, q="prism"))["hits"]
    assert hits == []
    hits = (await _all(client, "/api/v1/search", h, q="app"))["hits"]
    assert hits and all("prism" not in (x["title"] or "").lower() for x in hits)
    assert not any(x["kind"] == "subscription" for x in (await _all(client, "/api/v1/search", h, q="demo"))["hits"])

    viewer_logs = auth_headers("operator", oid=world.members["crm_prod_op"]["oid"])
    targets = await _all(client, "/api/v1/logs/targets", viewer_logs)
    assert targets and {t["environment_id"] for t in targets} == {world.crm_prod["id"]}
    r = await client.get("/api/v1/logs/queries", params={"resource_id": world.prism_app["id"]}, headers=viewer_logs)
    assert r.status_code == 404
    r = await client.post(
        "/api/v1/logs/query",
        json={"resource_id": world.prism_app["id"], "kql": "requests | take 1", "time_range": "1h"},
        headers=viewer_logs,
    )
    assert r.status_code == 404


async def test_environment_member_sees_only_that_environment(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("crm_prod_op")
    [project] = await _all(client, "/api/v1/projects", h)
    assert [e["id"] for e in project["environments"]] == [world.crm_prod["id"]]
    resources = (await _all(client, "/api/v1/resources", h, page_size=500))["items"]
    assert resources and {r["environment_id"] for r in resources} == {world.crm_prod["id"]}
    assert (await client.get(f"/api/v1/resources/{world.crm_dev_app['id']}", headers=h)).status_code == 404

    everyone = (await _all(client, "/api/v1/alerts", SA, page_size=200))["items"]
    dev_alert = next(a for a in everyone if a["resource_id"] == world.crm_dev_app["id"])
    prod_alert = next(a for a in everyone if a["resource_id"] == world.crm_app["id"])
    assert (await client.post(f"/api/v1/alerts/{dev_alert['id']}/acknowledge", headers=h)).status_code == 404
    assert (await client.post(f"/api/v1/alerts/{prod_alert['id']}/acknowledge", headers=h)).status_code == 200


async def test_resource_member_sees_exactly_their_resources(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("two_res")
    resources = (await _all(client, "/api/v1/resources", h, page_size=500))["items"]
    assert {r["id"] for r in resources} == {world.crm_app["id"], world.crm_plan["id"]}
    [project] = await _all(client, "/api/v1/projects", h)
    assert [e["id"] for e in project["environments"]] == [world.crm_prod["id"]]
    assert project["health"]["total"] == 2
    others = (await _all(client, "/api/v1/resources", SA, environment_id=world.crm_prod["id"], page_size=500))["items"]
    hidden = next(r for r in others if r["id"] not in {world.crm_app["id"], world.crm_plan["id"]})
    assert (await client.get(f"/api/v1/resources/{hidden['id']}", headers=h)).status_code == 404
    # The app's related plan is granted, so it is identified; a hidden relation would be null.
    detail = await _all(client, f"/api/v1/resources/{world.crm_app['id']}", h)
    assert detail["related"]["app_service_plan"] == world.crm_plan["id"]

    # A resource grant lasts only while the resource stays in the granted environment.
    moved = await client.put(
        f"/api/v1/resources/{world.crm_app['id']}/assignment",
        json={"project_id": world.crm["id"], "environment_id": world.crm_dev["id"]},
        headers=SA,
    )
    assert moved.status_code == 200
    assert (await client.get(f"/api/v1/resources/{world.crm_app['id']}", headers=h)).status_code == 404


async def test_member_without_grants_sees_nothing(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("nobody")
    me = await _all(client, "/api/v1/auth/me", h)
    assert me["access"] == {"unrestricted": False, "grants": []}
    assert await _all(client, "/api/v1/projects", h) == []
    assert (await _all(client, "/api/v1/resources", h))["total"] == 0
    assert (await _all(client, "/api/v1/alerts", h))["total"] == 0
    assert (await _all(client, "/api/v1/search", h, q="crm"))["hits"] == []
    overview = await _all(client, "/api/v1/overview", h)
    assert overview["totals"]["projects"] == 0 and overview["health"]["total"] == 0
    assert overview["recent_alerts"] == [] and overview["needs_attention"] == []


async def test_unrestricted_members_see_everything(client: httpx.AsyncClient, world: World) -> None:
    for headers in (SA, auth_headers("admin"), auth_headers("viewer")):
        assert {p["id"] for p in await _all(client, "/api/v1/projects", headers)} == {
            world.crm["id"],
            world.prism["id"],
        }
    me = await _all(client, "/api/v1/auth/me", auth_headers("admin"))
    assert me["access"]["unrestricted"] is True
    assert me["access"]["grants"][0]["project_id"] is None
    sa = await _all(client, "/api/v1/auth/me", SA)
    assert sa["access"] == {"unrestricted": True, "grants": []}


# ---------------------------------------------------------------- acting


async def test_scoped_admin_manages_only_their_project(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("prism_admin")
    prism, crm = world.prism["id"], world.crm["id"]

    created = await client.post("/api/v1/projects", json={"name": "New", "slug": "new", "environments": []}, headers=h)
    assert created.status_code == 403 and created.json()["error"]["code"] == "SCOPE_REQUIRED"
    # The name decides which project claims resources during discovery: renaming needs all projects.
    renamed = await client.patch(f"/api/v1/projects/{prism}", json={"name": "DATACORE"}, headers=h)
    assert renamed.status_code == 403 and renamed.json()["error"]["code"] == "SCOPE_REQUIRED"
    assert (await client.patch(f"/api/v1/projects/{prism}", json={"description": "Ours"}, headers=h)).status_code == 200
    tags = await client.patch(f"/api/v1/projects/{prism}", json={"tag_values": ["crm"]}, headers=h)
    assert tags.status_code == 403  # tags would claim other projects' resources
    assert (await client.patch(f"/api/v1/projects/{crm}", json={"name": "x"}, headers=h)).status_code == 404
    assert (await client.delete(f"/api/v1/projects/{crm}", headers=h)).status_code == 404
    env = await client.post(
        f"/api/v1/projects/{prism}/environments", json={"name": "UAT", "slug": "uat", "kind": "uat"}, headers=h
    )
    assert env.status_code == 201, env.text
    assert (
        await client.delete(f"/api/v1/projects/{crm}/environments/{world.crm_dev['id']}", headers=h)
    ).status_code == 404

    # Cannot pull a resource into PRISM from CRM, or push one out to CRM.
    pull = await client.put(
        f"/api/v1/resources/{world.crm_app['id']}/assignment",
        json={"project_id": prism, "environment_id": world.prism_prod["id"]},
        headers=h,
    )
    assert pull.status_code == 404
    push = await client.put(
        f"/api/v1/resources/{world.prism_app['id']}/assignment",
        json={"project_id": crm, "environment_id": world.crm_prod["id"]},
        headers=h,
    )
    assert push.status_code == 404
    unassign = await client.put(
        f"/api/v1/resources/{world.prism_app['id']}/assignment",
        json={"project_id": None, "environment_id": None},
        headers=h,
    )
    assert unassign.status_code == 403


async def test_scoped_admin_alert_configuration(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("prism_admin")
    rules = await _all(client, "/api/v1/alert-rules", h)
    assert [r["name"] for r in rules] == ["PRISM CPU"]
    base = {
        "name": "x",
        "monitor_key": "app_service",
        "metric_name": "plan_cpu",
        "aggregation": "Average",
        "operator": "gt",
        "threshold": 50,
        "severity": "warning",
        "window_minutes": 15,
    }
    other = await client.post("/api/v1/alert-rules", json={**base, "resource_id": world.crm_app["id"]}, headers=h)
    assert other.status_code == 422
    org_wide = await client.post("/api/v1/alert-rules", json=base, headers=h)
    assert org_wide.status_code == 403 and org_wide.json()["error"]["code"] == "SCOPE_REQUIRED"
    mine = await client.post("/api/v1/alert-rules", json={**base, "project_id": world.prism["id"]}, headers=h)
    assert mine.status_code == 201, mine.text

    org_cover = await client.post("/api/v1/alert-template-assignments", json={}, headers=h)
    assert org_cover.status_code == 403
    crm_cover = await client.post(
        "/api/v1/alert-template-assignments",
        json={"project_id": world.crm["id"], "environment_id": world.crm_prod["id"]},
        headers=h,
    )
    assert crm_cover.status_code == 422
    prism_cover = await client.post(
        "/api/v1/alert-template-assignments", json={"project_id": world.prism["id"]}, headers=h
    )
    assert prism_cover.status_code == 201, prism_cover.text
    assert [a["scope"] for a in await _all(client, "/api/v1/alert-template-assignments", h)] == ["project"]
    customise = await client.put(
        "/api/v1/alert-templates/app_service/rules/plan_cpu",
        json={"enabled": True, "info": 60, "warning": 70, "critical": 80},
        headers=h,
    )
    assert customise.status_code == 403

    export = await client.get("/api/v1/alert-rules/azure-export", headers=h)
    assert export.status_code == 200
    names = " ".join(a["name"] for t in export.json()["templates"] for a in t["template"]["resources"])
    assert "prism" in names and "crm" not in names
    assert (
        await client.get("/api/v1/alert-rules/azure-export", params={"project_id": world.crm["id"]}, headers=h)
    ).status_code == 404


async def test_organisation_settings_need_all_projects(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("prism_admin")
    for method, path in (
        ("GET", "/api/v1/azure/connections"),
        ("GET", "/api/v1/azure/subscriptions"),
        ("GET", "/api/v1/azure/identity"),
        ("POST", "/api/v1/azure/sync"),
        ("GET", "/api/v1/notification-channels"),
        ("GET", "/api/v1/notifications/teams-channels"),
        ("GET", "/api/v1/notifications/teams-setup"),
        ("GET", "/api/v1/notifications/email-lists"),
        ("GET", "/api/v1/notifications/email-status"),
        ("GET", "/api/v1/audit-logs"),
    ):
        r = await client.request(method, path, headers=h)
        assert r.status_code == 403, f"{method} {path}: {r.status_code}"
        assert r.json()["error"]["code"] == "SCOPE_REQUIRED", path
    # The unrestricted admin keeps them.
    assert (await client.get("/api/v1/azure/connections", headers=auth_headers("admin"))).status_code == 200


# ---------------------------------------------------------------- managing members


async def test_scoped_admin_manages_only_members_inside_their_access(client: httpx.AsyncClient, world: World) -> None:
    h = world.h("prism_admin")
    listed = {u["id"] for u in (await _all(client, "/api/v1/users", h, page_size=100))["items"]}
    assert {world.id("nobody"), world.id("prism_admin")} <= listed
    async with session_scope() as db:
        seeded_ids = {
            role: str(uid)
            for role in ("viewer", "super_admin")
            for uid in await db.scalars(select(User.id).where(User.entra_object_id == member_oid(role)))
        }
    # Outside PRISM: a CRM member, an all-projects member and a Super Admin.
    assert not listed & {world.id("crm_viewer"), seeded_ids["viewer"], seeded_ids["super_admin"]}
    assert (await client.get(f"/api/v1/users/{world.id('crm_viewer')}", headers=h)).status_code == 404

    everything = await client.post(
        "/api/v1/users/invite", json={"email": "a@example.test", "grants": [{"project_id": None}]}, headers=h
    )
    assert everything.status_code == 403 and everything.json()["error"]["code"] == "ACCESS_OUT_OF_SCOPE"
    crm_grant = await client.post(
        "/api/v1/users/invite", json={"email": "b@example.test", "grants": [{"project_id": world.crm["id"]}]}, headers=h
    )
    assert crm_grant.status_code == 422
    no_access = await client.post("/api/v1/users/invite", json={"email": "c@example.test"}, headers=h)
    assert no_access.status_code == 422 and no_access.json()["error"]["code"] == "ACCESS_REQUIRED"
    super_admin = await client.post(
        "/api/v1/users/invite", json={"email": "d@example.test", "role_key": "super_admin"}, headers=h
    )
    assert super_admin.status_code == 403
    ok = await client.post(
        "/api/v1/users/invite",
        json={"email": "e@example.test", "role_key": "operator", "grants": [{"project_id": world.prism["id"]}]},
        headers=h,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["access"]["grants"][0]["project_name"] == "PRISM"

    granted = await client.put(
        f"/api/v1/users/{world.id('nobody')}/access",
        json={"grants": [{"project_id": world.prism["id"], "environment_id": world.prism_prod["id"]}]},
        headers=h,
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["access"]["grants"][0]["environment_name"] == "Production"
    own = await client.put(f"/api/v1/users/{world.id('prism_admin')}/access", json={"grants": []}, headers=h)
    assert own.status_code == 422

    scope = await _all(client, "/api/v1/users/assignable-scope", h)
    assert scope["unrestricted"] is False
    assert [p["name"] for p in scope["projects"]] == ["PRISM"] and scope["projects"][0]["full"] is True
    assignable = await _all(
        client, f"/api/v1/users/assignable-scope/environments/{world.prism_prod['id']}/resources", h
    )
    expected = await _all(client, "/api/v1/resources", SA, environment_id=world.prism_prod["id"], page_size=500)
    assert assignable and {r["id"] for r in assignable} == {r["id"] for r in expected["items"]}
    hidden_env = await client.get(
        f"/api/v1/users/assignable-scope/environments/{world.crm_prod['id']}/resources", headers=h
    )
    assert hidden_env.status_code == 404


async def test_access_validation_and_normalisation(client: httpx.AsyncClient, world: World) -> None:
    target = world.id("nobody")
    crm, prod = world.crm["id"], world.crm_prod["id"]
    r = await client.put(
        f"/api/v1/users/{target}/access",
        json={
            "grants": [
                {"project_id": crm},
                {"project_id": crm, "environment_id": prod},
                {"project_id": crm, "environment_id": prod, "resource_id": world.crm_app["id"]},
                {"project_id": crm},
            ]
        },
        headers=SA,
    )
    assert r.status_code == 200, r.text
    assert [(g["project_name"], g["environment_id"]) for g in r.json()["access"]["grants"]] == [("CRM", None)]

    mismatched = await client.put(
        f"/api/v1/users/{target}/access",
        json={"grants": [{"project_id": world.prism["id"], "environment_id": prod}]},
        headers=SA,
    )
    assert mismatched.status_code == 422
    orphan = await client.put(
        f"/api/v1/users/{target}/access",
        json={"grants": [{"project_id": crm, "resource_id": world.crm_app["id"]}]},
        headers=SA,
    )
    assert orphan.status_code == 422
    sa_id = (await client.get("/api/v1/auth/me", headers=SA)).json()["id"]
    other_sa = await add_member("second-sa", role="super_admin")
    assert sa_id != str(other_sa)
    super_admin = await client.put(f"/api/v1/users/{other_sa}/access", json={"grants": []}, headers=SA)
    assert super_admin.status_code == 422

    audit = (await _all(client, f"/api/v1/users/{target}/audit", SA))["items"]
    changed = next(a for a in audit if a["action"] == "user.access_changed")
    assert changed["details"]["access"] == [{"project": "CRM", "environment": None, "resource": None}]


async def test_effective_coverage_is_visible_but_not_editable_for_members(
    client: httpx.AsyncClient, world: World
) -> None:
    """A member sees that broader coverage applies to their environment, without getting the coverage itself."""
    path = "/api/v1/alert-template-assignments/effective"
    mine = await client.get(path, params={"environment_id": world.crm_prod["id"]}, headers=world.h("crm_prod_op"))
    assert mine.status_code == 200, mine.text
    assert mine.json() == {"scope": "organization", "covered": True, "label": "All projects", "assignment": None}
    other = await client.get(path, params={"environment_id": world.prism_prod["id"]}, headers=world.h("crm_prod_op"))
    assert other.status_code == 404
    full = (await client.get(path, params={"environment_id": world.crm_prod["id"]}, headers=SA)).json()
    assert full["assignment"]["scope"] == "organization"


async def test_turning_coverage_off_overrides_broader_coverage(client: httpx.AsyncClient, world: World) -> None:
    open_template = {"status": "open", "page_size": 200}

    async def template_alerts(resource_id: str) -> list[dict[str, Any]]:
        items = (await client.get("/api/v1/alerts", params=open_template, headers=SA)).json()["items"]
        return [a for a in items if a["resource_id"] == resource_id and a["source"] == "template"]

    assert await template_alerts(world.crm_app["id"]), "the organisation-wide coverage raised alerts"

    off = await client.post(
        "/api/v1/alert-template-assignments", json={"resource_id": world.crm_app["id"], "enabled": False}, headers=SA
    )
    assert off.status_code == 201, off.text
    plan = (await client.get(f"/api/v1/resources/{world.crm_app['id']}/alert-plan", headers=SA)).json()
    assert plan["assignment"] is None
    me = (await client.get("/api/v1/auth/me", headers=SA)).json()
    async with session_scope() as db:
        await evaluate_alert_rules(db, get_azure_services(), uuid.UUID(me["organization_id"]), force=True)
    assert await template_alerts(world.crm_app["id"]) == []

    env_off = await client.post(
        "/api/v1/alert-template-assignments",
        json={"project_id": world.crm["id"], "environment_id": world.crm_dev["id"], "enabled": False},
        headers=SA,
    )
    assert env_off.status_code == 201, env_off.text
    effective = await client.get(
        "/api/v1/alert-template-assignments/effective", params={"environment_id": world.crm_dev["id"]}, headers=SA
    )
    assert effective.json()["scope"] == "environment" and effective.json()["covered"] is False


async def test_security_review_findings_stay_fixed(client: httpx.AsyncClient, world: World) -> None:
    """Regression tests for the independent review of scoped access."""
    # 1. Renaming a project cannot pull other projects' or unassigned resources into it.
    before = (await client.get("/api/v1/resources", params={"page_size": 1}, headers=world.h("prism_admin"))).json()
    r = await client.patch(
        f"/api/v1/projects/{world.prism['id']}", json={"name": "DATACORE"}, headers=world.h("prism_admin")
    )
    assert r.status_code == 403
    after = (await client.get("/api/v1/resources", params={"page_size": 1}, headers=world.h("prism_admin"))).json()
    assert after["total"] == before["total"]

    # 2. A member's audit history needs access to all projects.
    audit = await client.get(f"/api/v1/users/{world.id('crm_viewer')}/audit", headers=world.h("prism_admin"))
    assert audit.status_code in (403, 404)

    # 3. The alert plan does not hand organisation-wide coverage to a scoped member.
    plan = (
        await client.get(f"/api/v1/resources/{world.crm_app['id']}/alert-plan", headers=world.h("crm_prod_op"))
    ).json()
    assert plan["assignment"] is None and plan["rules"]

    # 4. A related resource outside the caller's access is not identified.
    only_app = await _member(
        client,
        "only_app",
        "operator",
        [{"project_id": world.crm["id"], "environment_id": world.crm_prod["id"], "resource_id": world.crm_app["id"]}],
    )
    h = auth_headers("operator", oid=only_app["oid"])
    metrics = await client.get(
        f"/api/v1/resources/{world.crm_app['id']}/metrics", params={"metrics": "plan_cpu", "timeRange": "1h"}, headers=h
    )
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["metrics"][0]["source_resource_id"] is None

    # 5. Inviting an out-of-scope user's email reveals nothing about them.
    sa_me = (await client.get("/api/v1/auth/me", headers=SA)).json()
    out_of_scope = await client.post(
        "/api/v1/users/invite",
        json={"email": "crm_viewer@example.test", "role_key": "viewer", "grants": [{"project_id": world.prism["id"]}]},
        headers=world.h("prism_admin"),
    )
    assert out_of_scope.status_code == 409
    assert out_of_scope.json()["error"]["message"] == "A user with this email address already exists."
    assert sa_me["access"]["unrestricted"] is True

    # 6. Organisation-level Azure details are not shown to scoped members.
    overview = (await client.get("/api/v1/overview", headers=world.h("nobody"))).json()
    assert overview["totals"]["subscriptions"] == 0 and overview["totals"]["connections"] == 0
    assert overview["service_health"] == []

    # 7. The same answer whether or not an out-of-scope resource exists.
    hidden = await client.get(f"/api/v1/dashboards/by-resource/{world.prism_app['id']}", headers=world.h("crm_viewer"))
    random = await client.get(f"/api/v1/dashboards/by-resource/{uuid.uuid4()}", headers=world.h("crm_viewer"))
    assert hidden.status_code == random.status_code == 404
    assert hidden.json()["error"]["message"] == random.json()["error"]["message"]

    # 8. Tag values (claim configuration) only for members with the whole project.
    projects = (await client.get("/api/v1/projects", headers=world.h("crm_prod_op"))).json()
    assert [p["tag_values"] for p in projects] == [[]]
