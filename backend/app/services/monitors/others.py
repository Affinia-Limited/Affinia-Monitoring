"""Monitors that use the default metric-driven dashboard layout.

These are intentionally data-only: each declares its metric catalogue and default
health thresholds, and the base class builds the dashboard.
"""

from __future__ import annotations

from app.services.monitors.base import AzureResourceMonitor, HealthRule, MetricDef


class StorageAccountMonitor(AzureResourceMonitor):
    key = "storage_account"
    display_name = "Storage Account"
    category = "Storage"
    resource_types = ("microsoft.storage/storageaccounts",)
    metrics = (
        MetricDef("availability", "Availability", "Availability", "percent", "Average"),
        MetricDef("transactions", "Transactions", "Transactions", "count", "Total"),
        MetricDef(
            "transactions_by_type",
            "Transactions",
            "Transactions by response",
            "count",
            "Total",
            split_by="ResponseType",
        ),
        MetricDef("e2e_latency", "SuccessE2ELatency", "End-to-end latency", "milliseconds", "Average"),
        MetricDef("server_latency", "SuccessServerLatency", "Server latency", "milliseconds", "Average"),
        MetricDef("ingress", "Ingress", "Ingress", "bytes", "Total"),
        MetricDef("egress", "Egress", "Egress", "bytes", "Total"),
        MetricDef("used_capacity", "UsedCapacity", "Used capacity", "bytes", "Average", min_interval_minutes=60),
    )
    health_rules = (HealthRule("availability", "lt", 99.9, 99.0, window_minutes=60),)
    summary_metrics = ("availability", "transactions", "e2e_latency", "used_capacity")


class KeyVaultMonitor(AzureResourceMonitor):
    key = "key_vault"
    display_name = "Key Vault"
    category = "Security"
    resource_types = ("microsoft.keyvault/vaults",)
    metrics = (
        MetricDef("availability", "Availability", "Availability", "percent", "Average"),
        MetricDef("api_hits", "ServiceApiHit", "API hits", "count", "Total"),
        MetricDef("api_latency", "ServiceApiLatency", "API latency", "milliseconds", "Average"),
        MetricDef("api_results", "ServiceApiResult", "API results by status", "count", "Total", split_by="StatusCode"),
        MetricDef("saturation", "SaturationShoebox", "Saturation", "percent", "Average"),
    )
    health_rules = (
        HealthRule("availability", "lt", 99.9, 99.0, window_minutes=60),
        HealthRule("saturation", "gt", 75, 90),
    )
    summary_metrics = ("availability", "api_hits", "api_latency", "saturation")


class ContainerRegistryMonitor(AzureResourceMonitor):
    key = "container_registry"
    display_name = "Container Registry"
    category = "Containers"
    resource_types = ("microsoft.containerregistry/registries",)
    metrics = (
        MetricDef("pulls", "TotalPullCount", "Pulls", "count", "Total"),
        MetricDef("successful_pulls", "SuccessfulPullCount", "Successful pulls", "count", "Total"),
        MetricDef("pushes", "TotalPushCount", "Pushes", "count", "Total"),
        MetricDef("successful_pushes", "SuccessfulPushCount", "Successful pushes", "count", "Total"),
        MetricDef("storage_used", "StorageUsed", "Storage used", "bytes", "Average", min_interval_minutes=60),
    )
    summary_metrics = ("pulls", "pushes", "storage_used")


class CosmosDbMonitor(AzureResourceMonitor):
    key = "cosmos_db"
    display_name = "Cosmos DB"
    category = "Databases"
    resource_types = ("microsoft.documentdb/databaseaccounts",)
    metrics = (
        MetricDef("requests", "TotalRequests", "Requests", "count", "Count"),
        MetricDef("requests_by_status", "TotalRequests", "Requests by status", "count", "Count", split_by="StatusCode"),
        MetricDef("request_units", "TotalRequestUnits", "Request units", "count", "Total"),
        MetricDef("normalized_ru", "NormalizedRUConsumption", "Normalized RU consumption", "percent", "Maximum"),
        MetricDef("availability", "ServiceAvailability", "Availability", "percent", "Average", min_interval_minutes=60),
        MetricDef("server_latency", "ServerSideLatency", "Server-side latency", "milliseconds", "Average"),
        MetricDef("data_usage", "DataUsage", "Data usage", "bytes", "Total"),
    )
    health_rules = (
        HealthRule("normalized_ru", "gt", 80, 95, reducer="max"),
        HealthRule("availability", "lt", 99.9, 99.0, window_minutes=60),
    )
    summary_metrics = ("requests", "normalized_ru", "server_latency", "availability")


class RedisMonitor(AzureResourceMonitor):
    key = "redis"
    display_name = "Azure Cache for Redis"
    category = "Databases"
    resource_types = ("microsoft.cache/redis",)
    metrics = (
        MetricDef("cpu", "percentProcessorTime", "CPU", "percent", "Maximum"),
        MetricDef("server_load", "serverLoad", "Server load", "percent", "Maximum"),
        MetricDef("memory", "usedmemorypercentage", "Memory used", "percent", "Maximum"),
        MetricDef("clients", "connectedclients", "Connected clients", "count", "Maximum"),
        MetricDef("hits", "cachehits", "Cache hits", "count", "Total"),
        MetricDef("misses", "cachemisses", "Cache misses", "count", "Total"),
        MetricDef("errors", "errors", "Errors", "count", "Maximum"),
    )
    health_rules = (
        HealthRule("server_load", "gt", 80, 95, reducer="max"),
        HealthRule("memory", "gt", 80, 95, reducer="max"),
    )
    summary_metrics = ("server_load", "memory", "clients", "hits")


class VirtualMachineMonitor(AzureResourceMonitor):
    key = "virtual_machine"
    display_name = "Virtual Machine"
    category = "Compute"
    resource_types = ("microsoft.compute/virtualmachines",)
    metrics = (
        MetricDef("cpu", "Percentage CPU", "CPU", "percent", "Average"),
        MetricDef("available_memory", "Available Memory Bytes", "Available memory", "bytes", "Average"),
        MetricDef("network_in", "Network In Total", "Network in", "bytes", "Total"),
        MetricDef("network_out", "Network Out Total", "Network out", "bytes", "Total"),
        MetricDef("disk_read", "Disk Read Bytes", "Disk read", "bytes", "Total"),
        MetricDef("disk_write", "Disk Write Bytes", "Disk write", "bytes", "Total"),
        MetricDef("availability", "VmAvailabilityMetric", "VM availability", "percent", "Average", scale=100.0),
    )
    health_rules = (
        HealthRule("cpu", "gt", 80, 90),
        HealthRule("availability", "lt", 100, 50, description="VM availability (%)"),
    )
    summary_metrics = ("cpu", "available_memory", "network_in", "network_out")


class AksMonitor(AzureResourceMonitor):
    key = "aks"
    display_name = "Kubernetes Service"
    category = "Containers"
    resource_types = ("microsoft.containerservice/managedclusters",)
    metrics = (
        MetricDef("node_cpu", "node_cpu_usage_percentage", "Node CPU", "percent", "Average"),
        MetricDef("node_memory", "node_memory_working_set_percentage", "Node memory", "percent", "Average"),
        MetricDef("pods_by_phase", "kube_pod_status_phase", "Pods by phase", "count", "Average", split_by="phase"),
        MetricDef(
            "nodes_by_condition",
            "kube_node_status_condition",
            "Nodes by condition",
            "count",
            "Average",
            split_by="condition",
        ),
        MetricDef(
            "inflight_requests",
            "apiserver_current_inflight_requests",
            "API server inflight requests",
            "count",
            "Average",
        ),
    )
    health_rules = (
        HealthRule("node_cpu", "gt", 80, 90),
        HealthRule("node_memory", "gt", 85, 95),
    )
    summary_metrics = ("node_cpu", "node_memory", "inflight_requests")


class ServiceBusMonitor(AzureResourceMonitor):
    key = "service_bus"
    display_name = "Service Bus"
    category = "Integration"
    resource_types = ("microsoft.servicebus/namespaces",)
    metrics = (
        MetricDef("incoming", "IncomingMessages", "Incoming messages", "count", "Total"),
        MetricDef("outgoing", "OutgoingMessages", "Outgoing messages", "count", "Total"),
        MetricDef("active", "ActiveMessages", "Active messages", "count", "Average"),
        MetricDef("dead_lettered", "DeadletteredMessages", "Dead-lettered messages", "count", "Average"),
        MetricDef("server_errors", "ServerErrors", "Server errors", "count", "Total"),
        MetricDef("user_errors", "UserErrors", "User errors", "count", "Total"),
        MetricDef("throttled", "ThrottledRequests", "Throttled requests", "count", "Total"),
    )
    health_rules = (
        HealthRule("dead_lettered", "gt", 10, 1000, reducer="max", description="Dead-lettered messages"),
        HealthRule("server_errors", "gt", 10, 50, reducer="sum", description="Server errors in 15 minutes"),
    )
    summary_metrics = ("incoming", "outgoing", "active", "dead_lettered")


class EventHubsMonitor(AzureResourceMonitor):
    key = "event_hubs"
    display_name = "Event Hubs"
    category = "Integration"
    resource_types = ("microsoft.eventhub/namespaces",)
    metrics = (
        MetricDef("incoming", "IncomingMessages", "Incoming messages", "count", "Total"),
        MetricDef("outgoing", "OutgoingMessages", "Outgoing messages", "count", "Total"),
        MetricDef("incoming_bytes", "IncomingBytes", "Incoming bytes", "bytes", "Total"),
        MetricDef("outgoing_bytes", "OutgoingBytes", "Outgoing bytes", "bytes", "Total"),
        MetricDef("throttled", "ThrottledRequests", "Throttled requests", "count", "Total"),
        MetricDef("server_errors", "ServerErrors", "Server errors", "count", "Total"),
    )
    health_rules = (
        HealthRule("throttled", "gt", 10, 100, reducer="sum", description="Throttled requests in 15 minutes"),
        HealthRule("server_errors", "gt", 10, 50, reducer="sum", description="Server errors in 15 minutes"),
    )
    summary_metrics = ("incoming", "outgoing", "throttled")


class ApplicationGatewayMonitor(AzureResourceMonitor):
    key = "application_gateway"
    display_name = "Application Gateway"
    category = "Networking"
    resource_types = ("microsoft.network/applicationgateways",)
    metrics = (
        MetricDef("requests", "TotalRequests", "Requests", "count", "Total"),
        MetricDef("failed_requests", "FailedRequests", "Failed requests", "count", "Total"),
        MetricDef(
            "responses_by_status", "ResponseStatus", "Responses by status", "count", "Total", split_by="HttpStatusGroup"
        ),
        MetricDef("healthy_hosts", "HealthyHostCount", "Healthy hosts", "count", "Average"),
        MetricDef("unhealthy_hosts", "UnhealthyHostCount", "Unhealthy hosts", "count", "Average"),
        MetricDef("total_time", "ApplicationGatewayTotalTime", "Total time", "milliseconds", "Average"),
        MetricDef("throughput", "Throughput", "Throughput", "bytes_per_second", "Average"),
    )
    health_rules = (
        HealthRule("unhealthy_hosts", "gt", 0, 1, reducer="max"),
        HealthRule("failed_requests", "gt", 10, 100, reducer="sum"),
    )
    summary_metrics = ("requests", "failed_requests", "healthy_hosts", "total_time")


class LoadBalancerMonitor(AzureResourceMonitor):
    key = "load_balancer"
    display_name = "Load Balancer"
    category = "Networking"
    resource_types = ("microsoft.network/loadbalancers",)
    metrics = (
        MetricDef("data_path_availability", "VipAvailability", "Data path availability", "percent", "Average"),
        MetricDef("health_probe_status", "DipAvailability", "Health probe status", "percent", "Average"),
        MetricDef("bytes", "ByteCount", "Bytes", "bytes", "Total"),
        MetricDef("packets", "PacketCount", "Packets", "count", "Total"),
        MetricDef("snat_connections", "SnatConnectionCount", "SNAT connections", "count", "Total"),
    )
    health_rules = (
        HealthRule("data_path_availability", "lt", 99, 90),
        HealthRule("health_probe_status", "lt", 90, 50),
    )
    summary_metrics = ("data_path_availability", "health_probe_status", "bytes")


class PublicIpMonitor(AzureResourceMonitor):
    key = "public_ip"
    display_name = "Public IP Address"
    category = "Networking"
    resource_types = ("microsoft.network/publicipaddresses",)
    metrics = (
        MetricDef("availability", "VipAvailability", "Data path availability", "percent", "Average"),
        MetricDef("bytes", "ByteCount", "Bytes", "bytes", "Total"),
        MetricDef("packets", "PacketCount", "Packets", "count", "Total"),
        MetricDef("ddos", "IfUnderDDoSAttack", "Under DDoS attack", "count", "Maximum"),
    )
    health_rules = (HealthRule("ddos", "gt", None, 0, reducer="max", description="Under DDoS attack"),)
    summary_metrics = ("availability", "bytes", "ddos")
