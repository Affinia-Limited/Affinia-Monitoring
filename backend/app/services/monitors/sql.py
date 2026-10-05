"""Azure SQL monitors (server, database, elastic pool)."""

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
    area,
    children_table,
    gauge,
    health_card,
    line,
    log_table,
    stat,
)

_DIAG = "AzureDiagnostics\n| where Category == '{category}'\n"


class SqlDatabaseMonitor(AzureResourceMonitor):
    key = "sql_database"
    display_name = "Azure SQL Database"
    category = "Databases"
    resource_types = ("microsoft.sql/servers/databases",)

    metrics = (
        MetricDef("cpu", "cpu_percent", "CPU", "percent", "Average"),
        MetricDef(
            "dtu",
            "dtu_consumption_percent",
            "DTU",
            "percent",
            "Average",
            description="Only reported for DTU-based service tiers.",
        ),
        MetricDef("data_io", "physical_data_read_percent", "Data IO", "percent", "Average"),
        MetricDef("log_io", "log_write_percent", "Log IO", "percent", "Average"),
        MetricDef("storage_percent", "storage_percent", "Storage used", "percent", "Maximum"),
        MetricDef("storage", "storage", "Data space used", "bytes", "Maximum"),
        MetricDef("sessions_percent", "sessions_percent", "Sessions", "percent", "Average"),
        MetricDef("sessions_count", "sessions_count", "Session count", "count", "Average"),
        MetricDef("workers", "workers_percent", "Workers", "percent", "Average"),
        MetricDef("connections_ok", "connection_successful", "Successful connections", "count", "Total"),
        MetricDef("connections_failed", "connection_failed", "Failed connections (system)", "count", "Total"),
        MetricDef(
            "connections_failed_user", "connection_failed_user_error", "Failed connections (user)", "count", "Total"
        ),
        MetricDef("blocked_firewall", "blocked_by_firewall", "Blocked by firewall", "count", "Total"),
        MetricDef("deadlocks", "deadlock", "Deadlocks", "count", "Total"),
        MetricDef("availability", "availability", "Availability", "percent", "Average"),
    )
    health_rules = (
        HealthRule("cpu", "gt", 80, 90, description="CPU"),
        HealthRule("dtu", "gt", 85, 95, description="DTU consumption"),
        HealthRule("storage_percent", "gt", 85, 95, reducer="max", description="Storage used"),
        HealthRule("log_io", "gt", 85, 95, description="Log IO"),
        HealthRule("deadlocks", "gt", 5, 20, reducer="sum", description="Deadlocks in 15 minutes"),
        HealthRule("connections_failed", "gt", 10, 50, reducer="sum", description="Failed connections"),
        HealthRule("availability", "lt", 99.9, 99.0, window_minutes=60, description="Availability (%)"),
    )
    log_queries = (
        LogQueryDef(
            "query_store_top_cpu",
            "Top queries by CPU (Query Store)",
            _DIAG.format(category="QueryStoreRuntimeStatistics")
            + "| summarize Executions = sum(count_executions_d), AvgCpuMs = round(avg(cpu_time_d) / 1000, 2),\n"
            "    AvgDurationMs = round(avg(duration_d) / 1000, 2) by query_hash_s\n| top 20 by AvgCpuMs",
            description="Requires the QueryStoreRuntimeStatistics diagnostic category.",
            category="Performance",
        ),
        LogQueryDef(
            "errors",
            "Errors",
            _DIAG.format(category="Errors")
            + "| project TimeGenerated, error_number_d, Severity, Message\n| order by TimeGenerated desc\n| take 200",
            severity_column="Severity",
            category="Diagnostics",
        ),
        LogQueryDef(
            "deadlocks",
            "Deadlocks",
            _DIAG.format(category="Deadlocks") + "| project TimeGenerated, Category, OperationName\n"
            "| order by TimeGenerated desc\n| take 100",
            category="Diagnostics",
        ),
        LogQueryDef(
            "timeouts",
            "Timeouts",
            _DIAG.format(category="Timeouts") + "| project TimeGenerated, query_hash_s, error_state_d\n"
            "| order by TimeGenerated desc\n| take 100",
            category="Diagnostics",
        ),
        LogQueryDef(
            "blocks",
            "Blocking",
            _DIAG.format(category="Blocks")
            + "| project TimeGenerated, duration_d, lock_mode_s, resource_owner_type_s\n"
            "| order by TimeGenerated desc\n| take 100",
            category="Diagnostics",
        ),
    )
    comparison = (
        ComparisonMetric("cpu", "avg", "SQL CPU"),
        ComparisonMetric("storage_percent", "max", "SQL storage"),
        ComparisonMetric("deadlocks", "sum", "SQL deadlocks"),
    )
    summary_metrics = ("cpu", "dtu", "storage_percent", "sessions_percent", "deadlocks")

    def matches(self, resource_type: str, kind: str | None, sku: str | None) -> bool:
        # The logical 'master' database is system-managed and reports no useful metrics. Azure marks it
        # with a "system" kind token (e.g. "v12.0,system,serverless") and a *SYSTEM SKU (e.g. GP_SYSTEM).
        kinds = {k.strip().lower() for k in (kind or "").split(",")}
        return (
            resource_type in self.resource_types
            and "system" not in kinds
            and not (sku or "").lower().endswith("system")
        )

    def sections(self) -> tuple[Section, ...]:
        return (
            Section(
                "Overview",
                (
                    gauge("cpu", "CPU"),
                    gauge("dtu", "DTU"),
                    gauge("storage_percent", "Storage"),
                    stat("deadlocks", "Deadlocks", "sum"),
                    line("CPU, DTU and IO", "cpu", "dtu", "data_io", "log_io", width=8),
                    health_card(),
                    line("Sessions and workers", "sessions_percent", "workers", width=6),
                    line("Availability", "availability", width=6),
                    alerts_table(width=12),
                ),
            ),
            Section(
                "Connections",
                (
                    stat("connections_ok", "Successful", "sum"),
                    stat("connections_failed", "Failed (system)", "sum"),
                    stat("connections_failed_user", "Failed (user)", "sum"),
                    stat("blocked_firewall", "Blocked by firewall", "sum"),
                    area("Connections", "connections_ok", "connections_failed", "connections_failed_user", width=8),
                    line("Session count", "sessions_count", width=4),
                    line("Deadlocks", "deadlocks", width=12),
                ),
            ),
            Section(
                "Storage",
                (
                    gauge("storage_percent", "Storage used"),
                    stat("storage", "Data space used", "max"),
                    Widget(
                        "property_card",
                        "Service objective",
                        3,
                        {"property": "currentServiceObjectiveName", "label": "Service objective"},
                    ),
                    Widget(
                        "property_card",
                        "Max size",
                        3,
                        {"property": "maxSizeBytes", "label": "Max size", "format": "bytes"},
                    ),
                    line("Data space used", "storage", width=12),
                ),
            ),
            Section(
                "Query performance",
                (
                    log_table("query_store_top_cpu", "Top queries by CPU"),
                    log_table("blocks", "Blocking", width=6),
                    log_table("timeouts", "Timeouts", width=6),
                ),
            ),
            Section(
                "Diagnostics",
                (
                    log_table("errors", "Errors"),
                    log_table("deadlocks", "Deadlocks"),
                ),
            ),
        )


class SqlServerMonitor(AzureResourceMonitor):
    key = "sql_server"
    display_name = "Azure SQL Server"
    category = "Databases"
    resource_types = ("microsoft.sql/servers",)

    def sections(self) -> tuple[Section, ...]:
        return (
            Section(
                "Overview",
                (
                    health_card(width=4),
                    Widget(
                        "property_card",
                        "Endpoint",
                        8,
                        {"property": "fullyQualifiedDomainName", "label": "Fully qualified domain name"},
                    ),
                    children_table("Databases", "children"),
                    alerts_table(width=12),
                ),
            ),
        )


class SqlElasticPoolMonitor(AzureResourceMonitor):
    key = "sql_elastic_pool"
    display_name = "SQL Elastic Pool"
    category = "Databases"
    resource_types = ("microsoft.sql/servers/elasticpools",)

    metrics = (
        MetricDef("cpu", "cpu_percent", "CPU", "percent", "Average"),
        MetricDef("dtu", "dtu_consumption_percent", "eDTU", "percent", "Average"),
        MetricDef("storage_percent", "storage_percent", "Storage used", "percent", "Maximum"),
        MetricDef("sessions_percent", "sessions_percent", "Sessions", "percent", "Average"),
        MetricDef("workers", "workers_percent", "Workers", "percent", "Average"),
    )
    health_rules = (
        HealthRule("cpu", "gt", 80, 90),
        HealthRule("storage_percent", "gt", 85, 95, reducer="max"),
    )
    summary_metrics = ("cpu", "dtu", "storage_percent")
