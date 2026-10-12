"""Email lists: management API, delivery providers and the alert / health triggers."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.session import session_scope
from app.models import Resource
from app.services.alerts.email_lists import HealthTransition, send_health_emails
from app.services.alerts.evaluator import evaluate_alert_rules
from app.services.azure.provider import get_azure_services
from app.services.email import clear_outbox, mask_email, sent_messages
from app.services.health.evaluator import evaluate_resources
from tests.conftest import auth_headers
from tests.helpers import find_resource, seeded

ADMIN = auth_headers("admin")
LISTS = "/api/v1/notifications/email-lists"


@pytest.fixture(autouse=True)
def log_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "email_provider", "log")
    monkeypatch.setattr(get_settings(), "public_base_url", "https://monitor.example")
    clear_outbox()
    yield
    clear_outbox()


async def _org_id(client: httpx.AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get("/api/v1/auth/me", headers=ADMIN)).json()["organization_id"])


async def _list(client: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {"name": "On-call", "recipients": ["Ops@Contoso.com", "lead@contoso.com"], **overrides}
    r = await client.post(LISTS, json=body, headers=ADMIN)
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


async def test_recipients_are_validated_and_normalised(client: httpx.AsyncClient) -> None:
    created = await _list(client, recipients=[" Ops@Contoso.com ", "ops@contoso.com", "lead@contoso.com"])
    assert created["recipients"] == ["ops@contoso.com", "lead@contoso.com"]
    assert created["min_severity"] == "critical" and created["notify_resolved"] is True

    for bad in (["not-an-address"], ["a@b"], [], ["x@contoso.com"] * 0 + [f"u{i}@contoso.com" for i in range(51)]):
        r = await client.post(LISTS, json={"name": "Bad", "recipients": bad}, headers=ADMIN)
        assert r.status_code == 422, bad
        # Rejected addresses are never echoed back.
        assert "not-an-address" not in r.text


async def test_scope_must_belong_to_the_organisation_and_project(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    crm, prism = data["crm"], data["prism"]
    prism_env = prism["environments"][0]["id"]
    wrong = await client.post(
        LISTS,
        json={"name": "x", "recipients": ["a@contoso.com"], "project_id": crm["id"], "environment_id": prism_env},
        headers=ADMIN,
    )
    assert wrong.status_code == 422
    orphan = await client.post(
        LISTS, json={"name": "x", "recipients": ["a@contoso.com"], "environment_id": prism_env}, headers=ADMIN
    )
    assert orphan.status_code == 422
    elsewhere = await client.post(
        LISTS,
        json={"name": "x", "recipients": ["a@contoso.com"], "project_id": crm["id"]},
        headers=auth_headers("admin", tenant="99999999-8888-4777-8666-555555555555"),
    )
    assert elsewhere.status_code == 422
    ok = await _list(client, project_id=prism["id"], environment_id=prism_env)
    assert ok["project_name"] == "PRISM" and ok["environment_id"] == prism_env


async def test_only_alert_managers_see_recipients(client: httpx.AsyncClient) -> None:
    await _list(client)
    for role in ("viewer", "operator"):
        assert (await client.get(LISTS, headers=auth_headers(role))).status_code == 403
        assert (
            await client.post(LISTS, json={"name": "x", "recipients": ["a@b.co"]}, headers=auth_headers(role))
        ).status_code == 403
    # Email lists never leak through the generic channel endpoints either.
    channels = (await client.get("/api/v1/notification-channels", headers=ADMIN)).json()
    assert all(c["channel_type"] != "email" for c in channels)
    generic = await client.post(
        "/api/v1/notification-channels",
        json={"name": "x", "channel_type": "email", "config": {"recipients": ["a@b.co"]}},
        headers=ADMIN,
    )
    assert generic.status_code == 422
    # Anyone who can see alerts may know whether email is configured (no addresses, no endpoints).
    status = (await client.get("/api/v1/notifications/email-status", headers=auth_headers("viewer"))).json()
    assert status == {"provider": "log", "configured": True}


async def test_update_and_delete(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    created = await _list(client, project_id=data["crm"]["id"])
    url = f"{LISTS}/{created['id']}"
    updated = (
        await client.patch(
            url,
            json={"name": "Platform team", "min_severity": "warning", "notify_resolved": False, "project_id": None},
            headers=ADMIN,
        )
    ).json()
    assert updated["name"] == "Platform team" and updated["min_severity"] == "warning"
    assert updated["notify_resolved"] is False and updated["project_id"] is None
    assert updated["recipients"] == created["recipients"]
    assert (await client.patch(url, json={"recipients": None}, headers=ADMIN)).status_code == 422
    assert (await client.delete(url, headers=ADMIN)).status_code == 204
    assert (await client.get(LISTS, headers=ADMIN)).json() == []
    assert (await client.patch(url, json={"name": "x"}, headers=ADMIN)).status_code == 404


async def test_audit_entries_mask_addresses(client: httpx.AsyncClient) -> None:
    created = await _list(client, recipients=["alice.smith@contoso.com"])
    await client.post(f"{LISTS}/{created['id']}/test", headers=ADMIN)
    logs = (await client.get("/api/v1/audit-logs", headers=ADMIN)).json()["items"]
    entries = [e for e in logs if e["action"].startswith("email_list.")]
    assert {e["action"] for e in entries} >= {"email_list.created", "email_list.tested"}
    assert "alice.smith@contoso.com" not in str(entries)
    assert "a***@contoso.com" in str(entries)
    assert mask_email("bob@x.io") == "b***@x.io"


# ---------------------------------------------------------------- delivery


async def test_test_email_is_sent_as_one_message(client: httpx.AsyncClient) -> None:
    created = await _list(client)
    result = (await client.post(f"{LISTS}/{created['id']}/test", headers=ADMIN)).json()
    assert result["status"] == "sent"
    [message] = sent_messages()
    assert set(message.recipients) == {"ops@contoso.com", "lead@contoso.com"}
    assert message.subject.startswith("[TEST]")
    assert "On-call" in message.text and "On-call" in message.html


async def test_without_a_provider_the_reason_is_clear(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await _list(client)
    monkeypatch.setattr(get_settings(), "email_provider", "none")
    result = (await client.post(f"{LISTS}/{created['id']}/test", headers=ADMIN)).json()
    assert result["status"] == "failed" and "not configured" in result["message"]
    status = (await client.get("/api/v1/notifications/email-status", headers=ADMIN)).json()
    assert status == {"provider": "none", "configured": False}


async def test_html_escapes_values(client: httpx.AsyncClient) -> None:
    created = await _list(client, name="<b>Ops</b>")
    await client.post(f"{LISTS}/{created['id']}/test", headers=ADMIN)
    [message] = sent_messages()
    assert "<b>Ops</b>" not in message.html and "&lt;b&gt;Ops&lt;/b&gt;" in message.html


def test_provider_settings_are_validated() -> None:
    base = {"environment": "test"}
    with pytest.raises(ValueError, match="ACS_EMAIL_ENDPOINT"):
        Settings(**base, email_provider="acs", email_sender_address="noreply@x.azurecomm.net")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="https"):
        Settings(
            **base,  # type: ignore[arg-type]
            email_provider="acs",
            acs_email_endpoint="http://x.communication.azure.com",
            email_sender_address="noreply@x.azurecomm.net",
        )
    ok = Settings(
        **base,  # type: ignore[arg-type]
        email_provider="acs",
        acs_email_endpoint="https://x.communication.azure.com",
        email_sender_address="noreply@x.azurecomm.net",
    )
    assert ok.email_provider == "acs"
    production = {
        "environment": "production",
        "entra_tenant_id": "t",
        "entra_client_id": "c",
        "entra_audience": "a",
        "redis_url": "rediss://cache.example:6380/0",
        "database_auth": "entra",
        "database_url": "postgresql+asyncpg://app@db.example:5432/monitoring",
        "azure_provider": "azure",
        "auth_mode": "entra",
        "task_backend": "celery",
    }
    with pytest.raises(ValueError, match="EMAIL_PROVIDER=log"):
        Settings(**production, email_provider="log")  # type: ignore[arg-type]


# ---------------------------------------------------------------- alert triggers


async def test_fired_and_resolved_alerts_are_emailed_by_severity_and_scope(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    org = await _org_id(client)
    crm, prism = data["crm"], data["prism"]
    everyone = await _list(client, name="Everyone", recipients=["all@contoso.com"])
    await _list(client, name="PRISM only", recipients=["prism@contoso.com"], project_id=prism["id"])
    quiet = await _list(client, name="No recovery", recipients=["quiet@contoso.com"], notify_resolved=False)
    crm_prod = next(e for e in crm["environments"] if e["slug"] == "prod")
    rule = await _rule(client, project_id=crm["id"], environment_id=crm_prod["id"])

    stats = await _evaluate_alerts(org)
    assert stats["fired"] >= 1
    fired = [m for m in sent_messages() if m.subject.startswith("[CRITICAL]")]
    recipients = {r for m in fired for r in m.recipients}
    # CRM alerts reach org-wide lists, not the PRISM-scoped one.
    assert recipients == {"all@contoso.com", "quiet@contoso.com"}
    assert all("CRM / Production" in m.subject for m in fired)
    assert all("https://monitor.example/resources/" in m.text for m in fired)

    # The alert's history records the email (list name only, no addresses).
    alerts = (await client.get("/api/v1/alerts", params={"status": "open"}, headers=ADMIN)).json()["items"]
    detail = (await client.get(f"/api/v1/alerts/{alerts[0]['id']}", headers=ADMIN)).json()
    notified = [e["message"] for e in detail["events"] if e["event_type"] == "notified"]
    assert any(everyone["name"] in m for m in notified) and "@" not in str(notified)

    clear_outbox()
    body = {k: rule[k] for k in ("name", "monitor_key", "metric_name", "aggregation", "operator", "severity")}
    await client.put(
        f"/api/v1/alert-rules/{rule['id']}",
        json={
            **body,
            "threshold": 1000,
            "window_minutes": 15,
            "project_id": crm["id"],
            "environment_id": crm_prod["id"],
        },
        headers=ADMIN,
    )
    stats = await _evaluate_alerts(org)
    assert stats["resolved"] >= 1
    resolved = [m for m in sent_messages() if m.subject.startswith("[RESOLVED]")]
    assert resolved and {r for m in resolved for r in m.recipients} == {"all@contoso.com"}
    assert quiet["notify_resolved"] is False


async def test_warning_alerts_reach_only_lists_that_want_warnings(client: httpx.AsyncClient) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _list(client, name="Critical only", recipients=["crit@contoso.com"])
    await _list(client, name="Everything", recipients=["all@contoso.com"], min_severity="warning")
    await _rule(client, severity="warning")
    await _evaluate_alerts(org)
    recipients = {r for m in sent_messages() for r in m.recipients}
    assert recipients == {"all@contoso.com"}


async def test_disabled_lists_are_not_emailed(client: httpx.AsyncClient) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _list(client, enabled=False)
    await _rule(client)
    await _evaluate_alerts(org)
    assert sent_messages() == []


# ---------------------------------------------------------------- health triggers


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
        await send_health_emails(db, org, transitions)
    return transitions


async def test_health_transitions_are_emailed_once_with_cooldown(client: httpx.AsyncClient) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _list(client, name="Warnings too", recipients=["ops@contoso.com"], min_severity="warning")
    # The demo's PRISM production plan runs hot (CPU warning).
    plan = await find_resource(client, "asp-prism-prod-uks")
    assert plan["health_status"] == "warning"

    transitions = await _reevaluate(org, plan["id"], status_before="healthy")
    assert [(t.previous, t.current) for t in transitions] == [("healthy", "warning")]
    [message] = sent_messages()
    assert message.subject.startswith("[WARNING]") and "asp-prism-prod-uks" in message.subject
    assert "CPU" in message.text

    # Steady state: no transition, no email.
    clear_outbox()
    assert await _reevaluate(org, plan["id"]) == []
    assert sent_messages() == []

    # Flapping back into warning within 30 minutes: the transition is seen, but not emailed again.
    assert len(await _reevaluate(org, plan["id"], status_before="healthy")) == 1
    assert sent_messages() == []


async def test_recovery_and_critical_only_lists(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _list(client, name="Critical only", recipients=["crit@contoso.com"])
    plan = await find_resource(client, "asp-prism-prod-uks")

    # Warning is below this list's severity.
    await _reevaluate(org, plan["id"], status_before="healthy")
    assert sent_messages() == []

    # Make the plan critical, then recover it.
    r = await client.put(
        "/api/v1/health-rules",
        json={"monitor_key": "app_service_plan", "metric_name": "cpu", "warning_threshold": 0, "critical_threshold": 1},
        headers=auth_headers("super_admin"),
    )
    assert r.status_code == 200
    await _reevaluate(org, plan["id"])
    [critical] = sent_messages()
    assert critical.subject.startswith("[CRITICAL]") and critical.recipients == ("crit@contoso.com",)

    clear_outbox()
    for metric in ("cpu", "memory"):
        await client.put(
            "/api/v1/health-rules",
            json={"monitor_key": "app_service_plan", "metric_name": metric, "enabled": False},
            headers=auth_headers("super_admin"),
        )
    transitions = await _reevaluate(org, plan["id"])
    assert [(t.previous, t.current) for t in transitions] == [("critical", "healthy")]
    [recovered] = sent_messages()
    assert recovered.subject.startswith("[RECOVERED]") and recovered.recipients == ("crit@contoso.com",)


async def test_manual_reevaluation_emails_after_commit(client: httpx.AsyncClient) -> None:
    await seeded(client)
    org = await _org_id(client)
    await _list(client, min_severity="warning")
    plan = await find_resource(client, "asp-prism-prod-uks")
    async with session_scope() as db:
        resource = await db.get(Resource, uuid.UUID(plan["id"]))
        assert resource is not None
        resource.health_status = "healthy"
    r = await client.post(f"/api/v1/resources/{plan['id']}/health/evaluate", headers=auth_headers("operator"))
    assert r.status_code == 200 and r.json()["health_status"] == "warning"
    assert [m.kind for m in sent_messages()] == ["health"]
    assert org


async def test_first_discovery_does_not_email(client: httpx.AsyncClient) -> None:
    """A brand-new estate's existing problems are shown on the dashboard, not mailed in bulk."""
    await _list(client, min_severity="warning")
    await seeded(client)
    assert sent_messages() == []
