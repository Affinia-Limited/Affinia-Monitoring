"""Azure Front Door monitors (Standard/Premium and classic)."""

from __future__ import annotations

from app.services.monitors.base import (
    AzureResourceMonitor,
    ComparisonMetric,
    HealthRule,
    LogQueryDef,
    MetricDef,
    Section,
    alerts_table,
    bars,
    gauge,
    health_card,
    line,
    log_chart,
    log_table,
    stat,
)

_ACCESS = "AzureDiagnostics\n| where Category == 'FrontDoorAccessLog'\n"
_WAF = "AzureDiagnostics\n| where Category == 'FrontDoorWebApplicationFirewallLog'\n"


class FrontDoorMonitor(AzureResourceMonitor):
    key = "front_door"
    display_name = "Azure Front Door"
    category = "Networking"
    resource_types = ("microsoft.cdn/profiles",)

    metrics = (
        MetricDef("requests", "RequestCount", "Requests", "count", "Total"),
        MetricDef(
            "requests_by_status", "RequestCount", "Requests by status", "count", "Total", split_by="HttpStatusGroup"
        ),
        MetricDef(
            "requests_by_country", "RequestCount", "Requests by country", "count", "Total", split_by="ClientCountry"
        ),
        MetricDef("percent_4xx", "Percentage4XX", "4xx rate", "percent", "Average"),
        MetricDef("percent_5xx", "Percentage5XX", "5xx rate", "percent", "Average"),
        MetricDef("total_latency", "TotalLatency", "Total latency", "milliseconds", "Average"),
        MetricDef("origin_latency", "OriginLatency", "Origin latency", "milliseconds", "Average"),
        MetricDef("origin_health", "OriginHealthPercentage", "Origin health", "percent", "Average"),
        MetricDef("origin_requests", "OriginRequestCount", "Origin requests", "count", "Total"),
        MetricDef(
            "origin_requests_by_status",
            "OriginRequestCount",
            "Origin requests by status",
            "count",
            "Total",
            split_by="HttpStatusGroup",
        ),
        MetricDef("response_size", "ResponseSize", "Bandwidth out", "bytes", "Total"),
        MetricDef("request_size", "RequestSize", "Bandwidth in", "bytes", "Total"),
        MetricDef(
            "waf_requests",
            "WebApplicationFirewallRequestCount",
            "WAF requests by action",
            "count",
            "Total",
            split_by="Action",
        ),
    )
    health_rules = (
        HealthRule("percent_5xx", "gt", 1, 5, description="5xx rate (%)"),
        HealthRule("origin_health", "lt", 90, 50, description="Origin health (%)"),
        HealthRule("total_latency", "gt", 1000, 3000, description="Total latency (ms)"),
    )
    log_queries = (
        LogQueryDef(
            "access_5xx_timeline",
            "5xx responses over time",
            _ACCESS + "| where toint(httpStatusCode_s) >= 500\n"
            "| summarize Errors = count() by bin(TimeGenerated, 5m)\n| order by TimeGenerated asc",
            visualization="timechart",
            category="Traffic",
        ),
        LogQueryDef(
            "access_logs",
            "Access logs",
            _ACCESS + "| project TimeGenerated, httpMethod_s, requestUri_s, httpStatusCode_s, timeTaken_s, "
            "clientCountry_s, originName_s\n| order by TimeGenerated desc\n| take 500",
            category="Traffic",
        ),
        LogQueryDef(
            "traffic_by_country",
            "Traffic by country",
            _ACCESS + "| summarize Requests = count() by clientCountry_s\n| top 25 by Requests",
            category="Traffic",
        ),
        LogQueryDef(
            "waf_blocked",
            "WAF blocked requests",
            _WAF + "| where action_s in~ ('Block', 'AnomalyScoring')\n"
            "| project TimeGenerated, action_s, ruleName_s, requestUri_s, policy_s\n"
            "| order by TimeGenerated desc\n| take 500",
            category="Security",
        ),
        LogQueryDef(
            "waf_top_rules",
            "Top WAF rules",
            _WAF + "| summarize Hits = count() by ruleName_s, action_s\n| top 20 by Hits",
            category="Security",
        ),
        LogQueryDef(
            "health_probes",
            "Origin health probe failures",
            "AzureDiagnostics\n| where Category == 'FrontDoorHealthProbeLog'\n| where result_s != 'Success'\n"
            "| project TimeGenerated, originName_s, result_s, httpStatusCode_s\n| order by TimeGenerated desc\n"
            "| take 200",
            category="Origins",
        ),
    )
    comparison = (
        ComparisonMetric("requests", "sum", "Front Door requests"),
        ComparisonMetric("percent_5xx", "avg", "Front Door 5xx rate"),
        ComparisonMetric("total_latency", "avg", "Front Door latency"),
    )
    summary_metrics = ("requests", "percent_5xx", "total_latency", "origin_health")

    def matches(self, resource_type: str, kind: str | None, sku: str | None) -> bool:
        return resource_type == "microsoft.cdn/profiles" and "azurefrontdoor" in (sku or "").lower()

    def sections(self) -> tuple[Section, ...]:
        return (
            Section(
                "Overview",
                (
                    stat("requests", "Requests", "sum"),
                    stat("percent_5xx", "5xx rate"),
                    stat("total_latency", "Latency"),
                    gauge("origin_health", "Origin health"),
                    bars("Requests by status class", "requests_by_status", width=8),
                    health_card(),
                    line("Latency", "total_latency", "origin_latency", width=6),
                    line("Error rates", "percent_4xx", "percent_5xx", width=6),
                    alerts_table(width=12),
                ),
            ),
            Section(
                "Origins",
                (
                    line("Origin health", "origin_health", width=6),
                    line("Origin latency", "origin_latency", width=6),
                    bars("Origin requests by status", "origin_requests_by_status", width=12),
                    log_table("health_probes", "Health probe failures"),
                ),
            ),
            Section(
                "Traffic",
                (
                    stat("response_size", "Bandwidth out", "sum"),
                    stat("request_size", "Bandwidth in", "sum"),
                    line("Bandwidth", "response_size", "request_size", width=6),
                    bars("Requests by country", "requests_by_country", width=6),
                    log_chart("access_5xx_timeline", "5xx responses (logs)", width=6),
                    log_table("traffic_by_country", "Traffic by country (logs)", width=6),
                    log_table("access_logs", "Access logs"),
                ),
            ),
            Section(
                "Security",
                (
                    bars("WAF activity by action", "waf_requests", width=12),
                    log_table("waf_top_rules", "Top WAF rules", width=6),
                    log_table("waf_blocked", "Blocked requests", width=6),
                ),
            ),
        )


class FrontDoorClassicMonitor(AzureResourceMonitor):
    key = "front_door_classic"
    display_name = "Azure Front Door (classic)"
    category = "Networking"
    resource_types = ("microsoft.network/frontdoors",)

    metrics = (
        MetricDef("requests", "RequestCount", "Requests", "count", "Total"),
        MetricDef(
            "requests_by_status", "RequestCount", "Requests by status", "count", "Total", split_by="HttpStatusGroup"
        ),
        MetricDef("total_latency", "TotalLatency", "Total latency", "milliseconds", "Average"),
        MetricDef("backend_latency", "BackendRequestLatency", "Backend latency", "milliseconds", "Average"),
        MetricDef("backend_health", "BackendHealthPercentage", "Backend health", "percent", "Average"),
        MetricDef("backend_requests", "BackendRequestCount", "Backend requests", "count", "Total"),
        MetricDef("response_size", "BillableResponseSize", "Bandwidth out", "bytes", "Total"),
        MetricDef(
            "waf_requests",
            "WebApplicationFirewallRequestCount",
            "WAF requests by action",
            "count",
            "Total",
            split_by="Action",
        ),
    )
    health_rules = (
        HealthRule("backend_health", "lt", 90, 50, description="Backend health (%)"),
        HealthRule("total_latency", "gt", 1000, 3000, description="Total latency (ms)"),
    )
    comparison = (ComparisonMetric("requests", "sum", "Front Door requests"),)
    summary_metrics = ("requests", "total_latency", "backend_health")

    def sections(self) -> tuple[Section, ...]:
        return (
            Section(
                "Overview",
                (
                    stat("requests", "Requests", "sum"),
                    stat("total_latency", "Latency"),
                    gauge("backend_health", "Backend health"),
                    stat("response_size", "Bandwidth out", "sum"),
                    bars("Requests by status class", "requests_by_status", width=8),
                    health_card(),
                    line("Latency", "total_latency", "backend_latency"),
                    bars("WAF activity", "waf_requests"),
                    alerts_table(width=12),
                ),
            ),
        )
