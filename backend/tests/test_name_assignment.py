"""Resources are placed in projects/environments by naming convention when tags do not decide."""

from __future__ import annotations

import uuid

import pytest

from app.models import Environment, Project
from app.services.discovery import assign


def _project(name: str, slug: str, tags: list[str] | None = None) -> Project:
    return Project(id=uuid.uuid4(), name=name, slug=slug, tag_values=tags or [slug])


def _envs(project: Project) -> list[Environment]:
    spec = [("Development", "dev", "development", ["dev", "development"]), ("UAT", "uat", "uat", ["uat"]),
            ("Production", "prod", "production", ["prod", "production"])]  # fmt: skip
    return [
        Environment(id=uuid.uuid4(), project_id=project.id, name=n, slug=s, kind=k, tag_values=t) for n, s, k, t in spec
    ]


CRM = _project("CRM", "crm")
PRISM = _project("PRISM", "prism")
PROJECTS = [CRM, PRISM]
ENVS = {CRM.id: _envs(CRM), PRISM.id: _envs(PRISM)}


def _place(name: str, group: str, tags: dict[str, str] | None = None) -> tuple[str | None, str | None, str]:
    pid, eid, source = assign(tags or {}, PROJECTS, ENVS, None, None, resource_name=name, resource_group=group)
    project = next((p.name for p in PROJECTS if p.id == pid), None)
    env = next((e.name for envs in ENVS.values() for e in envs if e.id == eid), None)
    return project, env, source


# Real names from the connected subscription.
@pytest.mark.parametrize(
    ("name", "group", "project", "env"),
    [
        ("app-crm-prod-uks", "rg-crm-prod-uks", "CRM", "Production"),
        ("crm_prod", "rg-crm-prod-uks", "CRM", "Production"),
        ("kv-crm-prod-uks", "rg-crm-prod-uks", "CRM", "Production"),
        ("afd-crm-prod-uks", "rg-crm-prod-uks", "CRM", "Production"),
        ("plan-app-crm-uat-uks", "rg-crm-uat-uks", "CRM", "UAT"),
        ("crm_dev", "rg-crm-lite-dev-uks", "CRM", "Development"),
        ("app-prism-dev-uks", "rg-prism-dev-uks", "PRISM", "Development"),
        ("kv-uat-prism-uks", "rg-prism-uat-uks", "PRISM", "UAT"),
        # No separators in the name: the resource group decides.
        ("acrprismdevuks", "rg-prism-dev-uks", "PRISM", "Development"),
        ("acrprismproduks", "rg-prism-prod-uks", "PRISM", "Production"),
        ("vm-prism-prod-uks-ip", "rg-prism-prod-uks", "PRISM", "Production"),
        # Project but no environment word.
        ("acrcrmshareduks", "rg-crm-shared-uks", "CRM", None),
        # Neither project: stays unassigned.
        ("kv-affinia-prod-01", "rg-affinia-prod-uksouth-01", None, None),
        ("datacorestorage", "rg-datacore-dev", None, None),
    ],
)
def test_naming_convention(name: str, group: str, project: str | None, env: str | None) -> None:
    placed = _place(name, group)
    assert placed[:2] == (project, env)
    assert placed[2] == ("name" if project else "none")


def test_whole_words_only() -> None:
    # "crm" inside another word is not the CRM project.
    assert _place("crmlando-api", "rg-crmlando-prod")[:2] == (None, None)
    # Two projects named in one resource: ambiguous, so not guessed.
    assert _place("link-crm-prism-prod", "rg-shared")[:2] == (None, None)


def test_tags_win_over_names() -> None:
    placed = _place("app-crm-prod-uks", "rg-crm-prod-uks", {"project": "prism", "environment": "uat"})
    assert placed == ("PRISM", "UAT", "tag")
    # A project tag without an environment tag: the environment still comes from the name.
    assert _place("app-crm-prod-uks", "rg-x", {"project": "crm"}) == ("CRM", "Production", "tag")


async def test_new_project_picks_up_existing_resources_immediately(client) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import auth_headers
    from tests.helpers import connect, create_project

    await connect(client)  # resources discovered before any project exists
    viewer = auth_headers("viewer")

    async def crm_total() -> int:
        page = (
            await client.get("/api/v1/resources", params={"q": "crm-prod", "page_size": 100}, headers=viewer)
        ).json()
        return sum(1 for r in page["items"] if r["project_name"] == "CRM" and r["environment_name"] == "Production")

    assert await crm_total() == 0
    await create_project(client, "crm")  # no sync in between
    assert await crm_total() > 0
