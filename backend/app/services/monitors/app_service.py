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
    log_chart,
    log_table,
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
    template_version = 2

    metrics = _SITE_METRICS
    health_rules = (
        HealthRule("plan_cpu", "gt", 80, 90, description="App Service Plan CPU"),
        HealthRule("plan_memory", "gt", 85, 95, description="App Service Plan memory"),
        HealthRule("http5xx", "gt", 10, 50, reducer="sum", description="HTTP 5xx responses in 15 minutes"),
        HealthRule("response_time", "gt", 1000, 3000, description="Average response time (ms)"),
        HealthRule("health_check", "lt", 95, 80, description="Health check pass rate (%)"),
    )
    log_queries = _HTTP_LOGS + _APP_INSIGHTS_LOGS
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
        return (
            Section(
                "Overview",
                (
                    gauge("plan_cpu", "CPU"),
                    gauge("plan_memory", "Memory"),
                    stat("requests", "Requests", "sum"),
                    stat("http5xx", "HTTP 5xx", "sum"),
                    line("CPU and memory", "plan_cpu", "plan_memory", width=8),
                    health_card(),
                    line("Requests", "requests", width=6),
                    line("Response time", "response_time", width=6),
                    alerts_table(width=12),
                ),
            ),
            Section(
                "HTTP",
                (
                    stat("http2xx", "2xx", "sum"),
                    stat("http3xx", "3xx", "sum"),
                    stat("http4xx", "4xx", "sum"),
                    stat("http5xx", "5xx", "sum"),
                    bars("Responses by status class", "http2xx", "http3xx", "http4xx", "http5xx", width=12),
                    log_chart("http_5xx_timeline", "HTTP 5xx (logs)"),
                    log_table("top_failing_paths", "Top failing paths", width=6),
                    log_table("http_logs", "HTTP logs"),
                ),
            ),
            Section(
                "Resources",
                (
                    stat("memory_working_set", "Memory working set"),
                    stat("cpu_time", "CPU time", "sum"),
                    stat("connections", "Connections"),
                    stat("plan_http_queue", "HTTP queue length", "max"),
                    line("Memory working set", "memory_working_set"),
                    line("Data in / out", "bytes_received", "bytes_sent"),
                    line("Health check status", "health_check"),
                    line("HTTP queue length", "plan_http_queue"),
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
                "Logs",
                (
                    log_table("app_logs", "Application logs"),
                    log_table("console_logs", "Console logs"),
                    log_table("platform_logs", "Platform events and restarts"),
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
