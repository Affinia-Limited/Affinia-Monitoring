"""App Service, Function App and App Service Plan monitors."""

from __future__ import annotations

from typing import Any, ClassVar

from app.services.monitors.base import (
    AzureResourceMonitor,
    ComparisonMetric,
    HealthRule,
    LogQueryDef,
    MetricDef,
    Section,
    Widget,
    alerts_table,
    bars,
    gauge,
    health_card,
    line,
    log_bars,
    log_chart,
    log_pie,
    log_stat,
    log_table,
    note,
    stat,
)

PLAN = "related:app_service_plan"
APP_INSIGHTS = "related:app_insights"

_SITE_METRICS: tuple[MetricDef, ...] = (
    MetricDef("requests", "Requests", "Requests", "count", "Total"),
    MetricDef("http2xx", "Http2xx", "HTTP 2xx", "count", "Total"),
    MetricDef("http3xx", "Http3xx", "HTTP 3xx", "count", "Total"),
    MetricDef("http4xx", "Http4xx", "HTTP 4xx", "count", "Total"),
    MetricDef("http5xx", "Http5xx", "HTTP 5xx", "count", "Total"),
    MetricDef("response_time", "HttpResponseTime", "Response time", "milliseconds", "Average", scale=1000.0),
    MetricDef("memory_working_set", "MemoryWorkingSet", "Memory working set", "bytes", "Average"),
    MetricDef("cpu_time", "CpuTime", "CPU time", "seconds", "Total"),
    MetricDef("health_check", "HealthCheckStatus", "Health check status", "percent", "Average"),
    MetricDef("bytes_received", "BytesReceived", "Data in", "bytes", "Total"),
    MetricDef("bytes_sent", "BytesSent", "Data out", "bytes", "Total"),
    MetricDef("file_system_usage", "FileSystemUsage", "Disk usage", "bytes", "Average"),
    MetricDef("io_read_bps", "IoReadBytesPerSecond", "Disk read", "bytes_per_second", "Average"),
    MetricDef("io_write_bps", "IoWriteBytesPerSecond", "Disk write", "bytes_per_second", "Average"),
    MetricDef("io_read_ops", "IoReadOperationsPerSecond", "Read operations", "countps", "Average"),
    MetricDef("io_write_ops", "IoWriteOperationsPerSecond", "Write operations", "countps", "Average"),
    MetricDef(
        "connections",
        "AppConnections",
        "Connections",
        "count",
        "Average",
        description="Windows App Service plans only.",
    ),
    MetricDef("plan_cpu", "CpuPercentage", "Plan CPU", "percent", "Average", target=PLAN),
    MetricDef("plan_memory", "MemoryPercentage", "Plan memory", "percent", "Average", target=PLAN),
    MetricDef("plan_http_queue", "HttpQueueLength", "HTTP queue length", "count", "Average", target=PLAN),
)

_HTTP_LOGS = (
    LogQueryDef(
        "http_5xx_timeline",
        "HTTP 5xx over time",
        "AppServiceHTTPLogs\n| where ScStatus >= 500\n| summarize Errors = count() by bin(TimeGenerated, 5m)\n"
        "| order by TimeGenerated asc",
        visualization="timechart",
        category="HTTP",
    ),
    LogQueryDef(
        "http_logs",
        "HTTP logs",
        "AppServiceHTTPLogs\n| project TimeGenerated, CsMethod, CsUriStem, ScStatus, TimeTaken, CsHost\n"
        "| order by TimeGenerated desc\n| take 500",
        category="HTTP",
    ),
    LogQueryDef(
        "top_failing_paths",
        "Top failing paths",
        "AppServiceHTTPLogs\n| where ScStatus >= 500\n| summarize Errors = count() by CsUriStem, ScStatus\n"
        "| top 20 by Errors",
        category="HTTP",
    ),
    LogQueryDef(
        "app_logs",
        "Application logs",
        "AppServiceAppLogs\n| project TimeGenerated, Level, Host, ResultDescription\n"
        "| order by TimeGenerated desc\n| take 500",
        severity_column="Level",
        category="Application",
    ),
    LogQueryDef(
        "console_logs",
        "Console logs",
        "AppServiceConsoleLogs\n| project TimeGenerated, Level, Host, ResultDescription\n"
        "| order by TimeGenerated desc\n| take 500",
        severity_column="Level",
        category="Application",
    ),
    LogQueryDef(
        "platform_logs",
        "Platform events and restarts",
        "AppServicePlatformLogs\n| project TimeGenerated, Level, OperationName, Message, ContainerId\n"
        "| order by TimeGenerated desc\n| take 200",
        severity_column="Level",
        description="Container starts, stops and restarts reported by the App Service platform.",
        category="Platform",
    ),
)

# Golden signals (traffic, errors, latency, saturation) from App Service HTTP logs. ``$__interval`` is
# replaced with a bucket size that suits the selected time range (about 120 points).
_HTTP = "AppServiceHTTPLogs\n"
_PUBLIC_CLIENTS = (
    "| where isnotempty(CIp) and not(ipv4_is_private(CIp)) and CIp !startswith '169.254'\n"
    "| extend Geo = geo_info_from_ip_address(CIp)\n"
)


def _q(key: str, title: str, kql: str, visualization: str = "table", category: str = "Golden signals") -> LogQueryDef:
    return LogQueryDef(key, title, _HTTP + kql, visualization=visualization, category=category)


_GOLDEN_SIGNALS = (
    # Service health (single values for the selected time range)
    _q(
        "sli_availability",
        "Availability",
        "| summarize Availability = round(100.0 * countif(ScStatus < 500) / count(), 3)",
    ),
    _q("sli_requests", "Total requests", "| summarize Requests = count()"),
    _q(
        "sli_error_rate",
        "Error rate (4xx + 5xx)",
        "| summarize ErrorRate = round(100.0 * countif(ScStatus >= 400) / count(), 2)",
    ),
    _q("sli_server_errors", "Server errors (5xx)", "| summarize ServerErrors = countif(ScStatus >= 500)"),
    _q("sli_p95", "p95 latency", "| summarize P95 = round(percentile(TimeTaken, 95), 0)"),
    _q(
        "sli_apdex",
        "Apdex (T = 500 ms)",
        "| summarize Satisfied = countif(TimeTaken <= 500),"
        " Tolerating = countif(TimeTaken > 500 and TimeTaken <= 2000), Total = count()\n"
        "| extend Apdex = round((Satisfied + Tolerating / 2.0) / Total, 2)",
    ),
    _q("sli_unique_visitors", "Unique visitors", "| summarize UniqueVisitors = dcount(CIp)"),
    _q("sli_avg_response", "Average response time", "| summarize AvgResponseMs = round(avg(TimeTaken), 0)"),
    _q(
        "success_vs_failure",
        "Request success vs failure",
        "| summarize Success = countif(ScStatus < 400), Failed = countif(ScStatus >= 400)",
    ),
    # Traffic and errors
    _q(
        "requests_by_status_class",
        "Request volume by status class",
        "| summarize ['2xx'] = countif(ScStatus < 300), ['3xx'] = countif(ScStatus between (300 .. 399)),"
        " ['4xx'] = countif(ScStatus between (400 .. 499)), ['5xx'] = countif(ScStatus >= 500)"
        " by bin(TimeGenerated, $__interval)\n| order by TimeGenerated asc",
        "timechart",
    ),
    _q(
        "error_rate_split",
        "Error rate: client vs server",
        "| summarize Total = count(), Client = countif(ScStatus between (400 .. 499)),"
        " Server = countif(ScStatus >= 500) by bin(TimeGenerated, $__interval)\n"
        "| project TimeGenerated, ['Client (4xx) %'] = round(100.0 * Client / Total, 2),"
        " ['Server (5xx) %'] = round(100.0 * Server / Total, 2)\n| order by TimeGenerated asc",
        "timechart",
    ),
    _q(
        "status_code_distribution",
        "Status code distribution",
        "| summarize Requests = count() by Status = tostring(ScStatus)\n| order by Requests desc",
    ),
    _q(
        "daily_traffic",
        "Daily traffic",
        "| summarize Requests = count() by bin(TimeGenerated, 1d)\n| order by TimeGenerated asc",
        "timechart",
    ),
    _q(
        "top_failing_routes",
        "Top failing routes",
        "| where ScStatus >= 400\n| summarize Errors = count() by Route = strcat(tostring(ScStatus), '  ', CsUriStem)\n"
        "| top 15 by Errors",
    ),
    _q(
        "request_rate",
        "Request rate over time",
        "| summarize Requests = count() by bin(TimeGenerated, $__interval)\n| order by TimeGenerated asc",
        "timechart",
    ),
    _q(
        "overall_error_rate",
        "Overall error rate (4xx + 5xx)",
        "| summarize Total = count(), Errors = countif(ScStatus >= 400) by bin(TimeGenerated, $__interval)\n"
        "| project TimeGenerated, ['Error rate %'] = round(100.0 * Errors / Total, 2)\n| order by TimeGenerated asc",
        "timechart",
    ),
    _q(
        "top_urls",
        "Top URLs being hit",
        "| summarize Hits = count() by Url = strcat(CsMethod, '  ', CsUriStem)\n| top 15 by Hits",
    ),
    # Latency
    _q(
        "latency_percentiles",
        "Response time percentiles",
        "| summarize p50 = percentile(TimeTaken, 50), p90 = percentile(TimeTaken, 90),"
        " p95 = percentile(TimeTaken, 95), p99 = percentile(TimeTaken, 99) by bin(TimeGenerated, $__interval)\n"
        "| order by TimeGenerated asc",
        "timechart",
    ),
    _q(
        "slowest_endpoints",
        "Slowest endpoints (by p95)",
        "| summarize Requests = count(), AvgMs = round(avg(TimeTaken), 0), P95Ms = round(percentile(TimeTaken, 95), 0),"
        " P99Ms = round(percentile(TimeTaken, 99), 0) by Endpoint = CsUriStem\n"
        "| where Requests >= 5\n| top 20 by P95Ms",
    ),
    # Endpoint breakdown
    _q(
        "endpoint_performance",
        "Endpoint performance",
        "| summarize Requests = count(), Errors = countif(ScStatus >= 400), ['5xx'] = countif(ScStatus >= 500),"
        " P50Ms = round(percentile(TimeTaken, 50), 0), P95Ms = round(percentile(TimeTaken, 95), 0),"
        " P99Ms = round(percentile(TimeTaken, 99), 0) by Method = CsMethod, Endpoint = CsUriStem\n"
        "| extend ['Error %'] = round(100.0 * Errors / Requests, 2)\n| order by Requests desc\n| take 50",
    ),
    # Clients and geography (public client addresses only)
    _q(
        "traffic_by_location",
        "Traffic by country and city",
        _PUBLIC_CLIENTS + "| summarize Requests = count(), UniqueIPs = dcount(CIp)"
        " by Country = tostring(Geo.country), City = tostring(Geo.city)\n| order by Requests desc\n| take 50",
        category="Clients",
    ),
    _q(
        "visitors_by_country",
        "Visitors by country",
        _PUBLIC_CLIENTS + "| summarize Visitors = dcount(CIp) by Country = tostring(Geo.country)\n| top 15 by Visitors",
        category="Clients",
    ),
    _q(
        "unique_clients",
        "Unique clients over time",
        "| summarize UniqueIPs = dcount(CIp) by bin(TimeGenerated, $__interval)\n| order by TimeGenerated asc",
        "timechart",
        category="Clients",
    ),
    _q(
        "top_client_ips",
        "Top client IPs by volume",
        "| where isnotempty(CIp)\n| summarize Requests = count(), Errors = countif(ScStatus >= 400),"
        " LastSeen = max(TimeGenerated) by ClientIP = CIp\n| top 20 by Requests",
        category="Clients",
    ),
    # Diagnostics
    _q(
        "recent_failed_requests",
        "Recent failed requests",
        "| where ScStatus >= 400\n| project TimeGenerated, Method = CsMethod, Endpoint = CsUriStem, Status = ScStatus,"
        " DurationMs = TimeTaken, ClientIP = CIp\n| order by TimeGenerated desc\n| take 200",
        category="HTTP",
    ),
)

_APP_INSIGHTS_LOGS = (
    LogQueryDef(
        "ai_requests_timeline",
        "Requests and failures",
        "requests\n| summarize Requests = count(), Failed = countif(success == false) by bin(timestamp, 5m)\n"
        "| order by timestamp asc",
        visualization="timechart",
        target=APP_INSIGHTS,
        category="Application Insights",
    ),
    LogQueryDef(
        "ai_failed_operations",
        "Failed operations",
        "requests\n| where success == false\n| summarize Failures = count(), AvgDurationMs = avg(duration) "
        "by operation_Name, resultCode\n| top 20 by Failures",
        target=APP_INSIGHTS,
        category="Application Insights",
    ),
    LogQueryDef(
        "ai_exceptions",
        "Recent exceptions",
        "exceptions\n| project timestamp, type, outerMessage, operation_Name, cloud_RoleName, severityLevel\n"
        "| order by timestamp desc\n| take 200",
        target=APP_INSIGHTS,
        severity_column="severityLevel",
        category="Application Insights",
    ),
    LogQueryDef(
        "ai_dependencies",
        "Dependencies",
        "dependencies\n| summarize Calls = count(), Failed = countif(success == false), "
        "AvgDurationMs = round(avg(duration), 1) by target, type\n| order by Calls desc\n| take 50",
        target=APP_INSIGHTS,
        category="Application Insights",
    ),
)


class AppServiceMonitor(AzureResourceMonitor):
    key = "app_service"
    display_name = "App Service"
    category = "Compute"
    resource_types = ("microsoft.web/sites",)
    #: 3: golden-signal layout (service health, traffic, latency, endpoints, saturation, clients, diagnostics).
    template_version = 3

    metrics = _SITE_METRICS
    health_rules = (
        HealthRule("plan_cpu", "gt", 80, 90, description="App Service Plan CPU"),
        HealthRule("plan_memory", "gt", 85, 95, description="App Service Plan memory"),
        HealthRule("http5xx", "gt", 10, 50, reducer="sum", description="HTTP 5xx responses in 15 minutes"),
        HealthRule("response_time", "gt", 1000, 3000, description="Average response time (ms)"),
        HealthRule("health_check", "lt", 95, 80, description="Health check pass rate (%)"),
    )
    log_queries = _HTTP_LOGS + _GOLDEN_SIGNALS + _APP_INSIGHTS_LOGS
    comparison: ClassVar[tuple[ComparisonMetric, ...]] = (
        ComparisonMetric("plan_cpu", "avg", "CPU"),
        ComparisonMetric("plan_memory", "avg", "Memory"),
        ComparisonMetric("requests", "sum", "Requests"),
        ComparisonMetric("http5xx", "sum", "5xx"),
        ComparisonMetric("response_time", "avg", "Response time"),
    )
    summary_metrics: ClassVar[tuple[str, ...]] = ("plan_cpu", "plan_memory", "requests", "http5xx", "response_time")

    def matches(self, resource_type: str, kind: str | None, sku: str | None) -> bool:
        return resource_type == "microsoft.web/sites" and "functionapp" not in (kind or "").lower()

    def related(self, resource_type: str, azure_id: str, properties: dict[str, Any]) -> dict[str, str]:
        relations: dict[str, str] = {}
        if properties.get("serverFarmId"):
            relations["app_service_plan"] = str(properties["serverFarmId"]).lower()
        if properties.get("appInsightsResourceId"):
            relations["app_insights"] = str(properties["appInsightsResourceId"]).lower()
        return relations

    def sections(self) -> tuple[Section, ...]:
        """Golden-signal layout. Log widgets need Diagnostic settings (AppServiceHTTPLogs, AppServiceConsoleLogs,
        AppServicePlatformLogs) sent to Log Analytics; platform-metric widgets work without any setup."""
        return (
            Section(
                "Service health",
                (
                    note(
                        "Service health",
                        "Headline service-level indicators for the selected time range, from HTTP logs.",
                    ),
                    log_stat("sli_availability", "Availability", unit="percent"),
                    log_stat("sli_requests", "Total requests"),
                    log_stat("sli_error_rate", "Error rate (4xx + 5xx)", unit="percent"),
                    log_stat("sli_server_errors", "Server errors (5xx)"),
                    log_stat("sli_p95", "p95 latency", unit="milliseconds"),
                    log_stat("sli_apdex", "Apdex (T = 500 ms)", unit="none", field="Apdex"),
                    log_stat("sli_unique_visitors", "Unique visitors", width=3),
                    stat("requests", "Requests (platform metric)", "sum"),
                    log_stat("sli_avg_response", "Average response time", unit="milliseconds", width=3),
                    log_pie("success_vs_failure", "Request success vs failure", width=3),
                    line("CPU and memory (plan)", "plan_cpu", "plan_memory", width=8),
                    health_card(),
                    alerts_table(width=12),
                ),
            ),
            Section(
                "Traffic and errors",
                (
                    note("Traffic and errors", "Request volume and failure rates, split by status class."),
                    log_chart("requests_by_status_class", "Request volume by status class", kind="bar", stacked=True),
                    log_chart("error_rate_split", "Error rate: client vs server", unit="percent"),
                    log_bars("status_code_distribution", "Status code distribution", width=3),
                    log_chart("daily_traffic", "Daily traffic", width=4, kind="bar"),
                    log_bars("top_failing_routes", "Top failing routes", width=5, horizontal=True),
                    log_chart("request_rate", "Request rate over time"),
                    line("Total HTTP requests (platform metric)", "requests"),
                    bars("HTTP response codes (platform metric)", "http2xx", "http3xx", "http4xx", "http5xx"),
                    log_chart("overall_error_rate", "Overall error rate (4xx + 5xx)", unit="percent"),
                    log_bars("top_urls", "Top URLs being hit", width=12, horizontal=True),
                ),
            ),
            Section(
                "Latency",
                (
                    note(
                        "Latency",
                        "Percentiles rather than averages: p95 and p99 describe user experience; the mean hides it.",
                    ),
                    log_chart("latency_percentiles", "Response time percentiles", unit="milliseconds"),
                    log_table("slowest_endpoints", "Slowest endpoints (by p95)", width=6),
                    line("Average response time (platform metric)", "response_time", width=12),
                ),
            ),
            Section(
                "Endpoints",
                (
                    note(
                        "Endpoint breakdown",
                        "One row per route: volume, error rate and latency percentiles side by side.",
                    ),
                    log_table("endpoint_performance", "Endpoint performance"),
                ),
            ),
            Section(
                "Saturation",
                (
                    note(
                        "Resource saturation",
                        "Platform metrics for this app and its App Service plan. No setup needed.",
                    ),
                    line("CPU time consumed", "cpu_time", width=4),
                    line("Memory working set", "memory_working_set", width=4),
                    line("Disk usage", "file_system_usage", width=4),
                    line("Network in and out", "bytes_received", "bytes_sent"),
                    line("Disk I/O throughput", "io_read_bps", "io_write_bps"),
                    line("I/O operations", "io_read_ops", "io_write_ops"),
                    line("Plan CPU and memory", "plan_cpu", "plan_memory"),
                    line("HTTP queue length (plan)", "plan_http_queue"),
                    line("Health check status", "health_check"),
                ),
            ),
            Section(
                "Clients",
                (
                    note(
                        "Clients and geography",
                        "Who is calling the service, from where, and at what volume. Locations come from the public "
                        "client IP address.",
                    ),
                    log_table("traffic_by_location", "Traffic by country and city", width=6),
                    log_bars("visitors_by_country", "Visitors by country", width=6, horizontal=True),
                    log_chart("unique_clients", "Unique clients over time"),
                    log_table("top_client_ips", "Top client IPs by volume", width=6),
                ),
            ),
            Section(
                "Application Insights",
                (
                    Widget("app_insights_status", "Application Insights", 12, {"relation": "app_insights"}),
                    log_chart("ai_requests_timeline", "Requests and failures", width=12),
                    log_table("ai_failed_operations", "Failed operations", width=6),
                    log_table("ai_dependencies", "Dependencies", width=6),
                    log_table("ai_exceptions", "Recent exceptions"),
                ),
            ),
            Section(
                "Diagnostics",
                (
                    note(
                        "Diagnostics",
                        "Raw log streams for investigation, once a panel above has told you where to look.",
                    ),
                    log_table("console_logs", "Live application logs (console)"),
                    log_table("platform_logs", "Platform events (crashes and restarts)"),
                    log_table("recent_failed_requests", "Recent failed requests"),
                    log_table("app_logs", "Application logs"),
                ),
            ),
        )


class FunctionAppMonitor(AppServiceMonitor):
    key = "function_app"
    display_name = "Function App"
    template_version = 1

    metrics = (
        *_SITE_METRICS,
        MetricDef("executions", "FunctionExecutionCount", "Executions", "count", "Total"),
        MetricDef("execution_units", "FunctionExecutionUnits", "Execution units", "count", "Total"),
    )
    summary_metrics = ("executions", "requests", "http5xx", "response_time")
    comparison = (
        ComparisonMetric("executions", "sum", "Function executions"),
        ComparisonMetric("http5xx", "sum", "5xx"),
    )

    def matches(self, resource_type: str, kind: str | None, sku: str | None) -> bool:
        return resource_type == "microsoft.web/sites" and "functionapp" in (kind or "").lower()

    def sections(self) -> tuple[Section, ...]:
        overview = Section(
            "Overview",
            (
                stat("executions", "Executions", "sum"),
                stat("execution_units", "Execution units", "sum"),
                stat("requests", "HTTP requests", "sum"),
                stat("http5xx", "HTTP 5xx", "sum"),
                line("Executions", "executions", width=8),
                health_card(),
                line("Response time", "response_time"),
                line("Memory working set", "memory_working_set"),
                alerts_table(width=12),
            ),
        )
        return (overview,) + AppServiceMonitor.sections(self)[3:]


class AppServicePlanMonitor(AzureResourceMonitor):
    key = "app_service_plan"
    display_name = "App Service Plan"
    category = "Compute"
    resource_types = ("microsoft.web/serverfarms",)

    metrics = (
        MetricDef("cpu", "CpuPercentage", "CPU", "percent", "Average"),
        MetricDef("memory", "MemoryPercentage", "Memory", "percent", "Average"),
        MetricDef("http_queue", "HttpQueueLength", "HTTP queue length", "count", "Average"),
        MetricDef("disk_queue", "DiskQueueLength", "Disk queue length", "count", "Average"),
        MetricDef("bytes_received", "BytesReceived", "Data in", "bytes", "Total"),
        MetricDef("bytes_sent", "BytesSent", "Data out", "bytes", "Total"),
    )
    health_rules = (
        HealthRule("cpu", "gt", 80, 90, description="CPU"),
        HealthRule("memory", "gt", 85, 95, description="Memory"),
    )
    summary_metrics = ("cpu", "memory", "http_queue")

    def sections(self) -> tuple[Section, ...]:
        return (
            Section(
                "Overview",
                (
                    gauge("cpu", "CPU"),
                    gauge("memory", "Memory"),
                    stat("http_queue", "HTTP queue", "max"),
                    stat("disk_queue", "Disk queue", "max"),
                    line("CPU and memory", "cpu", "memory", width=8),
                    health_card(),
                    Widget("property_card", "Instances", 4, {"property": "skuCapacity", "label": "Instances"}),
                    line("Queues", "http_queue", "disk_queue", width=8),
                    Widget("resource_table", "Apps on this plan", 12, {"relation": "apps_on_plan"}),
                    alerts_table(width=12),
                ),
            ),
        )
