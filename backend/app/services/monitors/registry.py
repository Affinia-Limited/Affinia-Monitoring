"""Monitor registry: resolves the plugin responsible for a discovered resource."""

from __future__ import annotations

from app.services.monitors.app_insights import AppInsightsMonitor
from app.services.monitors.app_service import AppServiceMonitor, AppServicePlanMonitor, FunctionAppMonitor
from app.services.monitors.base import AzureResourceMonitor, _check
from app.services.monitors.front_door import FrontDoorClassicMonitor, FrontDoorMonitor
from app.services.monitors.others import (
    AksMonitor,
    ApplicationGatewayMonitor,
    ContainerRegistryMonitor,
    CosmosDbMonitor,
    EventHubsMonitor,
    KeyVaultMonitor,
    LoadBalancerMonitor,
    PublicIpMonitor,
    RedisMonitor,
    ServiceBusMonitor,
    StorageAccountMonitor,
    VirtualMachineMonitor,
)
from app.services.monitors.sql import SqlDatabaseMonitor, SqlElasticPoolMonitor, SqlServerMonitor


class GenericMonitor(AzureResourceMonitor):
    """Fallback for discovered types without a dedicated monitor: inventory + Resource Health."""

    key = "generic"
    display_name = "Azure resource"
    category = "Other"


# Order matters where types overlap (e.g. Function Apps and App Services share microsoft.web/sites).
_MONITORS: tuple[AzureResourceMonitor, ...] = (
    AppServiceMonitor(),
    FunctionAppMonitor(),
    AppServicePlanMonitor(),
    SqlDatabaseMonitor(),
    SqlServerMonitor(),
    SqlElasticPoolMonitor(),
    FrontDoorMonitor(),
    FrontDoorClassicMonitor(),
    AppInsightsMonitor(),
    StorageAccountMonitor(),
    KeyVaultMonitor(),
    ContainerRegistryMonitor(),
    CosmosDbMonitor(),
    RedisMonitor(),
    VirtualMachineMonitor(),
    AksMonitor(),
    ServiceBusMonitor(),
    EventHubsMonitor(),
    ApplicationGatewayMonitor(),
    LoadBalancerMonitor(),
    PublicIpMonitor(),
)

GENERIC = GenericMonitor()

#: Friendly names for common discovered types that have no dedicated monitor.
TYPE_DISPLAY_NAMES: dict[str, str] = {
    "microsoft.network/virtualnetworks": "Virtual Network",
    "microsoft.network/networkinterfaces": "Network Interface",
    "microsoft.network/networksecuritygroups": "Network Security Group",
    "microsoft.operationalinsights/workspaces": "Log Analytics Workspace",
    "microsoft.network/frontdoorwebapplicationfirewallpolicies": "WAF Policy",
    "microsoft.managedidentity/userassignedidentities": "Managed Identity",
    "microsoft.compute/disks": "Managed Disk",
    "microsoft.insights/actiongroups": "Action Group",
    "microsoft.network/privateendpoints": "Private Endpoint",
    "microsoft.network/privatednszones": "Private DNS Zone",
}


def all_monitors() -> tuple[AzureResourceMonitor, ...]:
    return (*_MONITORS, GENERIC)


def get_monitor(key: str | None) -> AzureResourceMonitor:
    if key:
        for monitor in _MONITORS:
            if monitor.key == key:
                return monitor
    return GENERIC


def resolve_monitor(resource_type: str, kind: str | None, sku: str | None) -> AzureResourceMonitor:
    resource_type = resource_type.lower()
    for monitor in _MONITORS:
        if monitor.matches(resource_type, kind, sku):
            return monitor
    return GENERIC


def type_display_name(resource_type: str, monitor_key: str | None) -> str:
    monitor = get_monitor(monitor_key)
    if monitor is not GENERIC:
        return monitor.display_name
    if resource_type in TYPE_DISPLAY_NAMES:
        return TYPE_DISPLAY_NAMES[resource_type]
    # microsoft.foo/barBaz -> barBaz
    return resource_type.rsplit("/", 1)[-1]


def validate_all() -> None:
    keys: set[str] = set()
    for monitor in all_monitors():
        _check(monitor.key not in keys, f"duplicate monitor key {monitor.key}")
        keys.add(monitor.key)
        monitor.validate()
