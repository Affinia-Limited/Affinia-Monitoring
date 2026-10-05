"""MOCK DATA - a deterministic sample Azure estate for local development and tests.

Nothing here is used when ``AZURE_PROVIDER=azure``; configuration validation
refuses ``AZURE_PROVIDER=mock`` outside development/test environments.
"""

from __future__ import annotations

import zlib
from dataclasses import replace

from app.services.azure.types import DiscoveredResource, DiscoveredResourceGroup, SubscriptionInfo

MOCK_TENANT_ID = "00000000-0000-4000-8000-00000000d3a0"
MOCK_SUBSCRIPTIONS = (
    SubscriptionInfo("11111111-1111-4111-8111-111111111111", "Demo - Line of Business", MOCK_TENANT_ID, "Enabled"),
    SubscriptionInfo("22222222-2222-4222-8222-222222222222", "Demo - Data Platform", MOCK_TENANT_ID, "Enabled"),
)

# project -> (subscription index, environments)
_PROJECTS: dict[str, tuple[int, tuple[str, ...]]] = {
    "crm": (0, ("dev", "uat", "prod")),
    "prism": (0, ("dev", "prod")),
    "datacore": (1, ("dev", "uat", "prod")),
}
_ENV_TAG = {"dev": "Development", "uat": "UAT", "prod": "Production"}
_REGION = "uksouth"


def _rid(sub: str, rg: str, provider_type: str, name: str) -> str:
    return f"/subscriptions/{sub}/resourcegroups/{rg}/providers/{provider_type}/{name}".lower()


def _resources_for(project: str, env: str, sub: str) -> tuple[DiscoveredResourceGroup, list[DiscoveredResource]]:
    rg = f"rg-{project}-{env}-uks"
    tags = {"project": project.upper(), "environment": _ENV_TAG[env], "managed-by": "demo"}
    group = DiscoveredResourceGroup(
        azure_id=f"/subscriptions/{sub}/resourcegroups/{rg}", name=rg, subscription_id=sub, location=_REGION, tags=tags
    )

    def res(
        provider_type: str,
        name: str,
        *,
        kind: str | None = None,
        sku: str | None = None,
        location: str | None = _REGION,
        **props: object,
    ) -> DiscoveredResource:
        return DiscoveredResource(
            azure_id=_rid(sub, rg, provider_type, name),
            name=name,
            resource_type=provider_type.lower(),
            kind=kind,
            sku=sku,
            location=location,
            subscription_id=sub,
            resource_group=rg,
            tags=dict(tags),
            properties={"provisioningState": "Succeeded", **props},
        )

    plan_name = f"asp-{project}-{env}-uks"
    plan_id = _rid(sub, rg, "Microsoft.Web/serverfarms", plan_name)
    ai_name = f"appi-{project}-{env}-uks"
    ai_id = _rid(sub, rg, "Microsoft.Insights/components", ai_name)
    sql_server = f"sql-{project}-{env}-uks"
    capacity = 3 if env == "prod" else 1

    items = [
        res(
            "Microsoft.Web/serverfarms",
            plan_name,
            kind="linux",
            sku="P1v3" if env == "prod" else "B1",
            skuCapacity=capacity,
            skuTier="PremiumV3" if env == "prod" else "Basic",
        ),
        res(
            "Microsoft.Web/sites",
            f"app-{project}-{env}-uks",
            kind="app,linux",
            state="Running",
            serverFarmId=plan_id,
            appInsightsResourceId=ai_id,
            defaultHostName=f"app-{project}-{env}-uks.azurewebsites.net",
        ),
        res("Microsoft.Insights/components", ai_name, kind="web"),
        res(
            "Microsoft.Sql/servers",
            sql_server,
            kind="v12.0",
            fullyQualifiedDomainName=f"{sql_server}.database.windows.net",
        ),
        res(
            "Microsoft.Sql/servers/databases",
            f"{sql_server}/sqldb-{project}-{env}",
            kind="v12.0,user",
            sku="S2" if env == "prod" else "Basic",
            status="Online",
            currentServiceObjectiveName="S2" if env == "prod" else "Basic",
            maxSizeBytes=268435456000,
        ),
        res(
            "Microsoft.Sql/servers/databases",
            f"{sql_server}/master",
            kind="v12.0,system",
            sku="System",
            status="Online",
        ),
        res("Microsoft.KeyVault/vaults", f"kv-{project}-{env}-uks"),
        res("Microsoft.Storage/storageAccounts", f"st{project}{env}uks", kind="StorageV2", sku="Standard_LRS"),
        res(
            "Microsoft.OperationalInsights/workspaces",
            f"log-{project}-{env}-uks",
            customerId=f"{zlib.crc32(f'{project}-{env}'.encode()):08x}-0000-4000-8000-000000000000",
        ),
    ]
    if env in ("uat", "prod"):
        items.append(
            res(
                "Microsoft.Cdn/profiles",
                f"afd-{project}-{env}",
                sku="Premium_AzureFrontDoor",
                location="global",
                kind="frontdoor",
            )
        )
    if env in ("dev", "prod"):
        items.append(res("Microsoft.ContainerRegistry/registries", f"acr{project}{env}uks", sku="Standard"))
    if project == "datacore":
        items.append(
            res(
                "Microsoft.Web/sites",
                f"func-{project}-{env}-uks",
                kind="functionapp,linux",
                state="Running",
                serverFarmId=plan_id,
            )
        )
        items.append(res("Microsoft.ServiceBus/namespaces", f"sb-{project}-{env}-uks", sku="Standard"))
    if env == "prod":
        items.append(res("Microsoft.Network/virtualNetworks", f"vnet-{project}-{env}-uks"))
    # SQL database names in ARM are "<server>/<db>"; the display name is the db part.
    items = [replace(r, name=r.name.split("/")[-1]) if "/" in r.name else r for r in items]
    return group, items


def mock_estate(subscription_ids: list[str]) -> tuple[list[DiscoveredResourceGroup], list[DiscoveredResource]]:
    groups: list[DiscoveredResourceGroup] = []
    resources: list[DiscoveredResource] = []
    known = [s.subscription_id for s in MOCK_SUBSCRIPTIONS]
    for sub in subscription_ids:
        sub = sub.lower()
        if sub in known:
            index = known.index(sub)
            projects = [(p, envs) for p, (i, envs) in _PROJECTS.items() if i == index]
        else:
            # Any other subscription id gets a small generic estate so extra subscriptions can be demoed.
            projects = [("internal", ("dev", "prod"))]
        for project, envs in projects:
            for env in envs:
                group, items = _resources_for(project, env, sub)
                groups.append(group)
                resources.extend(items)
    return groups, resources
