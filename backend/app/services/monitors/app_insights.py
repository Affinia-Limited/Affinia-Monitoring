"""Application Insights component monitor.

Log queries run resource-centric against the component, so Azure only returns
telemetry belonging to that component. Table names use the Application Insights
schema (``requests``, ``exceptions``, ``dependencies``...), which is what
resource-centric queries against a component expose.
"""

from __future__ import annotations

from app.services.monitors.base import (
    AzureResourceMonitor,
    ComparisonMetric,
    HealthRule,
    LogQueryDef,
    MetricDef,
    Section,
    Widget,
    alerts_table,
    health_card,
    line,
    log_chart,
    log_table,
    stat,
)


class AppInsightsMonitor(AzureResourceMonitor):
    key = "app_insights"
    display_name = "Application Insights"
    category = "Monitoring"
    resource_types = ("microsoft.insights/components",)

    metrics = (
        MetricDef("requests", "requests/count", "Requests", "count", "Count"),
        MetricDef("failed_requests", "requests/failed", "Failed requests", "count", "Count"),
        MetricDef("response_time", "requests/duration", "Server response time", "milliseconds", "Average"),
        MetricDef("exceptions", "exceptions/count", "Exceptions", "count", "Count"),
        MetricDef("dependencies", "dependencies/count", "Dependency calls", "count", "Count"),
        MetricDef("dependency_failures", "dependencies/failed", "Dependency failures", "count", "Count"),
        MetricDef("dependency_duration", "dependencies/duration", "Dependency duration", "milliseconds", "Average"),
        MetricDef("availability", "availabilityResults/availabilityPercentage", "Availability", "percent", "Average"),
    )
    health_rules = (
        HealthRule("availability", "lt", 99, 95, window_minutes=30, description="Availability tests (%)"),
        HealthRule("failed_requests", "gt", 20, 100, reducer="sum", description="Failed requests in 15 minutes"),
        HealthRule("response_time", "gt", 1000, 3000, description="Server response time (ms)"),
    )
    log_queries = (
        LogQueryDef(
            "requests_timeline",
            "Requests and failures",
            "requests\n| summarize Requests = count(), Failed = countif(success == false) by bin(timestamp, 5m)\n"
            "| order by timestamp asc",
            visualization="timechart",
            category="Application",
        ),
        LogQueryDef(
            "slowest_operations",
            "Slowest operations",
            "requests\n| summarize Count = count(), P95Ms = round(percentile(duration, 95), 1), "
            "AvgMs = round(avg(duration), 1) by operation_Name\n| top 20 by P95Ms",
            category="Performance",
        ),
        LogQueryDef(
            "failed_operations",
            "Failed operations",
            "requests\n| where success == false\n| summarize Failures = count() by operation_Name, resultCode\n"
            "| top 20 by Failures",
            category="Failures",
        ),
        LogQueryDef(
            "exceptions",
            "Recent exceptions",
            "exceptions\n| project timestamp, type, outerMessage, operation_Name, cloud_RoleName, severityLevel\n"
            "| order by timestamp desc\n| take 200",
            severity_column="severityLevel",
            category="Failures",
        ),
        LogQueryDef(
            "exception_types",
            "Exceptions by type",
            "exceptions\n| summarize Count = count() by type\n| top 20 by Count",
            category="Failures",
        ),
        LogQueryDef(
            "dependencies",
            "Dependencies",
            "dependencies\n| summarize Calls = count(), Failed = countif(success == false), "
            "AvgDurationMs = round(avg(duration), 1) by target, type\n| order by Calls desc\n| take 50",
            category="Dependencies",
        ),
        LogQueryDef(
            "dependency_failures",
            "Dependency failures",
            "dependencies\n| where success == false\n| project timestamp, target, type, name, resultCode, duration\n"
            "| order by timestamp desc\n| take 200",
            category="Dependencies",
        ),
        LogQueryDef(
            "application_map",
            "Application map",
            "dependencies\n| summarize Calls = count(), Failed = countif(success == false), "
            "AvgDurationMs = round(avg(duration), 1) by Source = cloud_RoleName, Target = target, Type = type\n"
            "| order by Calls desc\n| take 100",
            description="Calls between application roles and their dependencies.",
            category="Application",
        ),
        LogQueryDef(
            "availability_results",
            "Availability test results",
            "availabilityResults\n| summarize Runs = count(), Passed = countif(success == true), "
            "AvgDurationMs = round(avg(duration), 1) by name, location\n| order by name asc",
            category="Availability",
        ),
        LogQueryDef(
            "traces",
            "Trace logs",
            "traces\n| project timestamp, severityLevel, message, operation_Name, cloud_RoleName\n"
            "| order by timestamp desc\n| take 500",
            severity_column="severityLevel",
            category="Logs",
        ),
    )
    comparison = (
        ComparisonMetric("failed_requests", "sum", "Failed requests"),
        ComparisonMetric("exceptions", "sum", "Exceptions"),
    )
    summary_metrics = ("requests", "failed_requests", "response_time", "exceptions", "availability")

    def sections(self) -> tuple[Section, ...]:
        return (
            Section(
                "Application",
                (
                    stat("requests", "Requests", "sum"),
                    stat("failed_requests", "Failed requests", "sum"),
                    stat("response_time", "Response time"),
                    stat("availability", "Availability"),
                    log_chart("requests_timeline", "Requests and failures", width=8),
                    health_card(),
                    Widget("dependency_map", "Application map", 12, {"query": "application_map"}),
                    alerts_table(width=12),
                ),
            ),
            Section(
                "Performance",
                (
                    line("Server response time", "response_time", width=12),
                    log_table("slowest_operations", "Slowest operations"),
                ),
            ),
            Section(
                "Failures",
                (
                    line("Failed requests and exceptions", "failed_requests", "exceptions", width=12),
                    log_table("failed_operations", "Failed operations", width=6),
                    log_table("exception_types", "Exceptions by type", width=6),
                    log_table("exceptions", "Recent exceptions"),
                ),
            ),
            Section(
                "Dependencies",
                (
                    line("Dependency calls and failures", "dependencies", "dependency_failures", width=6),
                    line("Dependency duration", "dependency_duration", width=6),
                    log_table("dependencies", "Dependencies"),
                    log_table("dependency_failures", "Dependency failures"),
                ),
            ),
            Section(
                "Availability",
                (
                    line("Availability", "availability", width=12),
                    log_table("availability_results", "Availability test results"),
                ),
            ),
            Section("Logs", (log_table("traces", "Trace logs"),)),
        )
