"""Microsoft Teams alert channels: management API, alert and health-change delivery, de-duplication."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db.session import session_scope
from app.models import Resource
from app.services.alerts.email_lists import HealthTransition
from app.services.alerts.evaluator import evaluate_alert_rules
from app.services.alerts.teams_alerts import notify_health_transitions
from app.services.azure.provider import get_azure_services
from app.services.health.evaluator import evaluate_resources
from tests.conftest import auth_headers
from tests.helpers import find_resource, seeded

ADMIN = auth_headers("admin")
TEAMS = "/api/v1/notifications/teams-channels"
#: Test organisations are slugged org-0, org-1, ...; secrets must carry that prefix.
SECRET = "org-0-teams-alerts"
WEBHOOK = "https://example.test/workflows/teams"


@pytest.fixture
def posts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every Teams card that would have been posted (nothing leaves the test)."""
    sent: list[dict[str, Any]] = []

    async def fake_post(url: str, body: dict[str, Any]) -> None:
        assert url == WEBHOOK
        sent.append(body["attachments"][0]["content"])

    monkeypatch.setenv("SECRET_ORG_0_TEAMS_ALERTS", WEBHOOK)
    monkeypatch.setattr("app.services.alerts.channels.registry._post", fake_post)
    return sent


def _summary(card: dict[str, Any]) -> str:
    return str(card["body"][0]["text"])


async def _org_id(client: httpx.AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get("/api/v1/auth/me", headers=ADMIN)).json()["organization_id"])


async def _channel(client: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    r = await client.post(TEAMS, json={"name": "Ops channel", "secret_ref": SECRET, **overrides}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


async def _rule(client: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {
        "name": "High plan CPU",
        "monitor_key": "app_service",
        "metric_name": "plan_cpu",
        "aggregation": "Average",
        "operator": "gt",
        "threshold": 1,
        "severity": "critical",
        "window_minutes": 15,
        **overrides,
    }
    r = await client.post("/api/v1/alert-rules", json=body, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


async def _evaluate_alerts(org: uuid.UUID) -> dict[str, int]:
    async with session_scope() as db:
        return await evaluate_alert_rules(db, get_azure_services(), org)


# ---------------------------------------------------------------- management


async def test_setup_reports_the_secret_prefix_and_source(client: httpx.AsyncClient) -> None:
    setup = (await client.get("/api/v1/notifications/teams-setup", headers=ADMIN)).json()
    assert setup == {"secret_prefix": "org-0-", "secret_source": "environment"}
    assert (await client.get("/api/v1/notifications/teams-setup", headers=auth_headers("viewer"))).status_code == 403


async def test_channels_are_validated_and_managed(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    other_prefix = await client.post(TEAMS, json={"name": "x", "secret_ref": "contoso-teams"}, headers=ADMIN)
    assert other_prefix.status_code == 422 and "org-0-" in other_prefix.json()["error"]["message"]
    url_as_secret = await client.post(TEAMS, json={"name": "x", "secret_ref": WEBHOOK}, headers=ADMIN)
    assert url_as_secret.status_code == 422
    prism_prod = next(e for e in data["prism"]["environments"] if e["slug"] == "prod")
    mismatched = await client.post(
        TEAMS,
        json={"name": "x", "secret_ref": SECRET, "project_id": data["crm"]["id"], "environment_id": prism_prod["id"]},
        headers=ADMIN,
    )
    assert mismatched.status_code == 422
    assert (
        await client.post(TEAMS, json={"name": "x", "secret_ref": SECRET}, headers=auth_headers("viewer"))
    ).status_code == 403

    created = await _channel(client, project_id=data["prism"]["id"])
    assert created["min_severity"] == "critical" and created["notify_resolved"] is True
    assert created["project_name"] == "PRISM" and created["secret_ref"] == SECRET

    updated = await client.patch(
        f"{TEAMS}/{created['id']}",
        json={"min_severity": "warning", "notify_resolved": False, "project_id": None},
        headers=ADMIN,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["min_severity"] == "warning" and updated.json()["project_id"] is None
    assert (await client.patch(f"{TEAMS}/{created['id']}", json={"name": None}, headers=ADMIN)).status_code == 422

    # Still a normal channel: alert rules can name it and the generic list shows it.
    generic = (await client.get("/api/v1/notification-channels", headers=ADMIN)).json()
    assert [c["id"] for c in generic] == [created["id"]]

    assert (await client.delete(f"{TEAMS}/{created['id']}", headers=ADMIN)).status_code == 204
    assert (await client.get(TEAMS, headers=ADMIN)).json() == []


async def test_test_message_posts_to_the_channel(client: httpx.AsyncClient, posts: list[dict[str, Any]]) -> None:
    channel = await _channel(client)
    r = await client.post(f"/api/v1/notification-channels/{channel['id']}/test", headers=ADMIN)
    assert r.json()["status"] == "sent", r.text
    assert "Test notification" in _summary(posts[0])


# ---------------------------------------------------------------- alert delivery


async def test_alerts_are_posted_by_severity_and_scope(client: httpx.AsyncClient, posts: list[dict[str, Any]]) -> None:
    data = await seeded(client)
    org = await _org_id(client)
    await _channel(client, name="CRM", project_id=data["crm"]["id"])
    await _rule(client, project_id=data["crm"]["id"])
    await _rule(client, name="Warning rule", severity="warning")

    await _evaluate_alerts(org)
    summaries = [_summary(c) for c in posts]
    # Critical CRM alerts only: the warning rule and other projects stay quiet.
    assert summaries and all(s.startswith("[CRITICAL] CRM /") for s in summaries)
    facts = {f["title"]: f["value"] for f in posts[0]["body"][1]["facts"]}
    assert facts["Severity"] == "critical" and facts["Resource"]


async def test_rule_named_channel_is_not_posted_twice(client: httpx.AsyncClient, posts: list[dict[str, Any]]) -> None:
    await seeded(client)
    org = await _org_id(client)
    channel = await _channel(client)
    app = await find_resource(client, "app-crm-prod-uks")
    await _rule(client, resource_id=app["id"], notification_channel_ids=[channel["id"]])
    await _evaluate_alerts(org)
    assert len(posts) == 1


async def test_rule_only_teams_channels_keep_working(client: httpx.AsyncClient, posts: list[dict[str, Any]]) -> None:
    """Teams channels created through Notification channels post only for the rules that name them."""
    await seeded(client)
    org = await _org_id(client)
    legacy = await client.post(
        "/api/v1/notification-channels",
        json={"name": "Legacy", "channel_type": "teams", "secret_ref": SECRET},
        headers=ADMIN,
    )
    assert legacy.status_code == 201, legacy.text
    app = await find_resource(client, "app-crm-prod-uks")
    await _rule(
        client, name="Named", resource_id=app["id"], severity="warning", notification_channel_ids=[legacy.json()["id"]]
    )
    await _rule(client, name="Unnamed")
    await _evaluate_alerts(org)
    assert [_summary(c).startswith("[WARNING]") for c in posts] == [True]


# ---------------------------------------------------------------- health changes


async def _reevaluate(org: uuid.UUID, resource_id: str, status_before: str | None = None) -> list[HealthTransition]:
    transitions: list[HealthTransition] = []
    async with session_scope() as db:
        if status_before:
            resource = await db.scalar(select(Resource).where(Resource.id == uuid.UUID(resource_id)))
            assert resource is not None
            resource.health_status = status_before
            await db.flush()
        await evaluate_resources(
            db, get_azure_services(), org, resource_ids=[uuid.UUID(resource_id)], transitions=transitions
        )
    async with session_scope() as db:
        await notify_health_transitions(db, org, transitions)
    return transitions


async def test_health_changes_are_posted_once_with_cooldown(
    client: httpx.AsyncClient, posts: list[dict[str, Any]]
) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _channel(client, name="Warnings too", min_severity="warning")
    plan = await find_resource(client, "asp-prism-prod-uks")
    assert plan["health_status"] == "warning"

    await _reevaluate(org, plan["id"], status_before="healthy")
    assert len(posts) == 1
    assert _summary(posts[0]).startswith("[WARNING] PRISM / Production - asp-prism-prod-uks needs attention")

    # Steady state, then flapping back within the cooldown: nothing more is posted.
    await _reevaluate(org, plan["id"])
    await _reevaluate(org, plan["id"], status_before="healthy")
    assert len(posts) == 1


async def test_critical_only_channels_ignore_warnings(client: httpx.AsyncClient, posts: list[dict[str, Any]]) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _channel(client)
    plan = await find_resource(client, "asp-prism-prod-uks")
    await _reevaluate(org, plan["id"], status_before="healthy")
    assert posts == []


async def test_production_reads_env_secrets_only_when_allowed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Self-hosted servers without Key Vault can opt in to SECRET_ variables in production."""
    from app.core.config import Environment, get_settings
    from app.services.secrets import SecretNotAvailableError, get_secret

    settings = get_settings()
    monkeypatch.setattr(settings, "environment", Environment.production)
    monkeypatch.setattr(settings, "key_vault_url", None)
    monkeypatch.setenv("SECRET_ORG_0_TEAMS_ALERTS", WEBHOOK)

    with pytest.raises(SecretNotAvailableError):
        await get_secret(SECRET)
    setup = (await client.get("/api/v1/notifications/teams-setup", headers=ADMIN)).json()
    assert setup["secret_source"] == "none"

    monkeypatch.setattr(settings, "allow_env_secrets", True)
    assert await get_secret(SECRET) == WEBHOOK
    setup = (await client.get("/api/v1/notifications/teams-setup", headers=ADMIN)).json()
    assert setup["secret_source"] == "environment"
