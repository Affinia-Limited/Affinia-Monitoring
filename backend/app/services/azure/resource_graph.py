"""Azure Resource Graph and ARM subscription access (real implementation)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from azure.mgmt.resource.subscriptions.aio import SubscriptionClient
from azure.mgmt.resourcegraph.aio import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from app.services.azure.credentials import CredentialProvider
from app.services.azure.errors import azure_call
from app.services.azure.types import (
    DiscoveredResource,
    DiscoveredResourceGroup,
    ResourceChange,
    ResourceHealthState,
    ServiceHealthEvent,
    SubscriptionInfo,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 1000
_MAX_PAGES = 100  # 100k resources per sync is a hard safety cap
_SUBSCRIPTION_BATCH = 100  # Resource Graph accepts up to 1000; keep requests modest

# Only these properties are captured. Resource properties are allow-listed so that
# nothing unexpected (and potentially sensitive) is copied into the database.
DISCOVERY_QUERY = """
resources
| extend
    provisioningState = tostring(properties.provisioningState),
    state = tostring(properties.state),
    status = tostring(properties.status),
    defaultHostName = tostring(properties.defaultHostName),
    serverFarmId = tolower(tostring(properties.serverFarmId)),
    currentServiceObjectiveName = tostring(properties.currentServiceObjectiveName),
    maxSizeBytes = tolong(properties.maxSizeBytes),
    fullyQualifiedDomainName = tostring(properties.fullyQualifiedDomainName),
    workspaceResourceId = tolower(tostring(properties.WorkspaceResourceId)),
    appInsightsResourceId = tolower(tostring(tags['hidden-link: /app-insights-resource-id'])),
    customerId = tostring(properties.customerId),
    vmSize = tostring(properties.hardwareProfile.vmSize),
    kubernetesVersion = tostring(properties.kubernetesVersion),
    skuName = tostring(sku.name),
    skuCapacity = toint(sku.capacity),
    skuTier = tostring(sku.tier)
| project id = tolower(id), name, type = tolower(type), kind, location, resourceGroup = tolower(resourceGroup),
    subscriptionId, tags, skuName, skuTier, skuCapacity, provisioningState, state, status, defaultHostName,
    serverFarmId,
    currentServiceObjectiveName, maxSizeBytes, fullyQualifiedDomainName, workspaceResourceId,
    appInsightsResourceId, customerId, vmSize, kubernetesVersion
| order by id asc
"""

RESOURCE_GROUP_QUERY = """
resourcecontainers
| where type =~ 'microsoft.resources/subscriptions/resourcegroups'
| project id = tolower(id), name, location, subscriptionId, tags
| order by id asc
"""

RESOURCE_HEALTH_QUERY = """
healthresources
| where type =~ 'microsoft.resourcehealth/availabilitystatuses'
| project targetResourceId = tolower(tostring(properties.targetResourceId)),
    availabilityState = tostring(properties.availabilityState),
    summary = tostring(properties.summary),
    reasonType = tostring(properties.reasonType),
    occurredTime = tostring(properties.occuredTime)
"""

# Column names are prefixed (evt*) because bare names such as `title` fail to parse inside `project`
# in Resource Graph. Impact is returned raw and flattened in Python.
SERVICE_HEALTH_QUERY = """
servicehealthresources
| where type =~ 'microsoft.resourcehealth/events'
| extend evtType = tostring(properties.EventType), evtStatus = tostring(properties.Status),
    evtTitle = tostring(properties.Title), evtLevel = tostring(properties.EventLevel),
    evtUpdated = todatetime(properties.LastUpdateTime), evtImpact = properties.Impact
| where evtStatus =~ 'Active' or evtUpdated > ago(7d)
| project evtId = name, evtTitle, evtType, evtStatus, evtLevel, evtUpdated, subscriptionId, evtImpact
| order by evtUpdated desc
| take 50
"""

RECENT_CHANGES_QUERY = """
resourcechanges
| extend changeTime = todatetime(properties.changeAttributes.timestamp),
    targetResourceId = tolower(tostring(properties.targetResourceId)),
    changeType = tostring(properties.changeType),
    changedBy = tostring(properties.changeAttributes.changedBy),
    operation = tostring(properties.changeAttributes.operation)
| where changeTime > ago(7d)
| project targetResourceId, changeType, changeTime, changedBy, operation
| order by changeTime desc
| take {limit}
"""


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _impacted(impact: Any) -> tuple[list[str], list[str]]:
    """Flatten Service Health ``Impact`` into (services, regions), preserving order without duplicates."""
    services: list[str] = []
    regions: list[str] = []
    for item in impact if isinstance(impact, list) else []:
        if not isinstance(item, dict):
            continue
        service = item.get("ImpactedService")
        if service and service not in services:
            services.append(str(service))
        for region in item.get("ImpactedRegions") or []:
            name = region.get("ImpactedRegion") if isinstance(region, dict) else None
            if name and name not in regions:
                regions.append(str(name))
    return services, regions


def _clean_tags(tags: Any) -> dict[str, str]:
    if not isinstance(tags, dict):
        return {}
    return {str(k): str(v) for k, v in tags.items() if not str(k).startswith("hidden-")}


_PROPERTY_KEYS = (
    "provisioningState",
    "state",
    "status",
    "defaultHostName",
    "serverFarmId",
    "currentServiceObjectiveName",
    "maxSizeBytes",
    "fullyQualifiedDomainName",
    "workspaceResourceId",
    "appInsightsResourceId",
    "customerId",
    "vmSize",
    "kubernetesVersion",
    "skuTier",
    "skuCapacity",
)


def row_to_resource(row: dict[str, Any]) -> DiscoveredResource:
    properties = {key: row.get(key) for key in _PROPERTY_KEYS if row.get(key) not in (None, "")}
    return DiscoveredResource(
        azure_id=str(row["id"]).lower(),
        name=str(row["name"]),
        resource_type=str(row["type"]).lower(),
        kind=row.get("kind") or None,
        sku=row.get("skuName") or None,
        location=row.get("location") or None,
        subscription_id=str(row["subscriptionId"]),
        resource_group=str(row.get("resourceGroup") or ""),
        tags=_clean_tags(row.get("tags")),
        properties=properties,
    )


class AzureResourceGraphService:
    def __init__(self, credentials: CredentialProvider):
        self._credentials = credentials

    async def _query(self, tenant_id: str, subscription_ids: list[str], query: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        credential = self._credentials.for_tenant(tenant_id)
        async with ResourceGraphClient(credential) as client:
            for start in range(0, len(subscription_ids), _SUBSCRIPTION_BATCH):
                batch = subscription_ids[start : start + _SUBSCRIPTION_BATCH]
                skip_token: str | None = None
                for _ in range(_MAX_PAGES):
                    request = QueryRequest(
                        query=query,
                        subscriptions=batch,
                        options=QueryRequestOptions(top=_PAGE_SIZE, skip_token=skip_token, result_format="objectArray"),
                    )
                    async with azure_call("resource_graph.query"):
                        response = await client.resources(request)
                    # objectArray format always returns a list of row objects.
                    if isinstance(response.data, list):
                        rows.extend(response.data)
                    skip_token = response.skip_token
                    if not skip_token:
                        break
                else:
                    logger.warning("resource_graph_page_cap_reached", extra={"pages": _MAX_PAGES})
        return rows

    async def list_subscriptions(self, tenant_id: str) -> list[SubscriptionInfo]:
        credential = self._credentials.for_tenant(tenant_id)
        results: list[SubscriptionInfo] = []
        async with SubscriptionClient(credential) as client:
            async with azure_call("arm.list_subscriptions"):
                async for sub in client.subscriptions.list():
                    results.append(
                        SubscriptionInfo(
                            subscription_id=str(sub.subscription_id),
                            display_name=str(sub.display_name or ""),
                            tenant_id=str(sub.tenant_id or tenant_id),
                            state=str(sub.state or "Unknown"),
                        )
                    )
        return results

    async def get_subscription(self, tenant_id: str, subscription_id: str) -> SubscriptionInfo:
        credential = self._credentials.for_tenant(tenant_id)
        async with SubscriptionClient(credential) as client:
            async with azure_call("arm.get_subscription"):
                sub = await client.subscriptions.get(subscription_id)
        return SubscriptionInfo(
            subscription_id=str(sub.subscription_id),
            display_name=str(sub.display_name or ""),
            tenant_id=str(sub.tenant_id or tenant_id),
            state=str(sub.state or "Unknown"),
        )

    async def discover_resource_groups(
        self, tenant_id: str, subscription_ids: list[str]
    ) -> list[DiscoveredResourceGroup]:
        rows = await self._query(tenant_id, subscription_ids, RESOURCE_GROUP_QUERY)
        return [
            DiscoveredResourceGroup(
                azure_id=str(r["id"]).lower(),
                name=str(r["name"]),
                subscription_id=str(r["subscriptionId"]),
                location=r.get("location"),
                tags=_clean_tags(r.get("tags")),
            )
            for r in rows
        ]

    async def discover_resources(self, tenant_id: str, subscription_ids: list[str]) -> list[DiscoveredResource]:
        rows = await self._query(tenant_id, subscription_ids, DISCOVERY_QUERY)
        return [row_to_resource(r) for r in rows]

    async def resource_health(self, tenant_id: str, subscription_ids: list[str]) -> list[ResourceHealthState]:
        rows = await self._query(tenant_id, subscription_ids, RESOURCE_HEALTH_QUERY)
        return [
            ResourceHealthState(
                azure_id=str(r["targetResourceId"]).lower(),
                availability_state=str(r.get("availabilityState") or "Unknown"),
                summary=r.get("summary") or None,
                reason_type=r.get("reasonType") or None,
                occurred_at=_parse_dt(r.get("occurredTime")),
            )
            for r in rows
            if r.get("targetResourceId")
        ]

    async def service_health(self, tenant_id: str, subscription_ids: list[str]) -> list[ServiceHealthEvent]:
        rows = await self._query(tenant_id, subscription_ids, SERVICE_HEALTH_QUERY)
        return [
            ServiceHealthEvent(
                event_id=str(r.get("evtId")),
                title=str(r.get("evtTitle") or ""),
                event_type=str(r.get("evtType") or ""),
                status=str(r.get("evtStatus") or ""),
                level=r.get("evtLevel") or None,
                services=_impacted(r.get("evtImpact"))[0],
                regions=_impacted(r.get("evtImpact"))[1],
                last_update=_parse_dt(r.get("evtUpdated")),
                subscription_id=str(r.get("subscriptionId") or ""),
            )
            for r in rows
        ]

    async def recent_changes(
        self, tenant_id: str, subscription_ids: list[str], limit: int = 50
    ) -> list[ResourceChange]:
        query = RECENT_CHANGES_QUERY.format(limit=max(1, min(int(limit), 200)))
        rows = await self._query(tenant_id, subscription_ids, query)
        return [
            ResourceChange(
                azure_id=str(r.get("targetResourceId") or ""),
                change_type=str(r.get("changeType") or ""),
                changed_at=_parse_dt(r.get("changeTime")),
                changed_by=r.get("changedBy") or None,
                operation=r.get("operation") or None,
            )
            for r in rows
        ]
