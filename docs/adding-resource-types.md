# Adding a resource type

Discovery already finds every resource type in a subscription. Anything without a dedicated monitor is shown through the `generic` monitor: inventory, tags, properties, Resource Health and alerts. Adding a monitor plugin adds metrics, health rules, log queries, environment comparison and a dashboard. **No API, database or frontend changes are needed.**

## Plugin anatomy

A plugin is a subclass of `AzureResourceMonitor` (`backend/app/services/monitors/base.py`) that declares data:

| Attribute / method | Purpose |
| --- | --- |
| `key` | Stable identifier stored on resources (`monitor_key`) and used in alert rules |
| `display_name`, `category` | Shown in the UI, and matched by global search ("Front Door" finds Front Door resources) |
| `resource_types` | Lower-cased ARM types |
| `matches(resource_type, kind, sku)` | Optional finer matching, for example on kind or SKU |
| `metrics` | `MetricDef(key, name, label, unit, aggregation, namespace=None, split_by=None, scale=1.0, target="self")` |
| `health_rules` | `HealthRule(metric, operator, warning, critical, window_minutes=15, reducer="avg")` |
| `log_queries` | `LogQueryDef(...)` (see [dashboard-templates.md](dashboard-templates.md#log-query-definitions)) |
| `comparison` | `ComparisonMetric(metric, rollup, label)` rows in the environment comparison |
| `summary_metrics` | Keys highlighted on the default overview |
| `related()` | Relation name to ARM ID of related resources, from discovery properties |
| `sections()` | Curated layout. If omitted, a default layout is built from `metrics` |
| `template_version` | Optional explicit version. Definition changes bump the stored version automatically |

Units after scaling: `percent`, `count`, `milliseconds`, `seconds`, `bytes`, `bytes_per_second`, `countps`.

`validate_all()` runs at start-up and in the tests. It fails if any health rule, comparison, summary or widget references an unknown metric or log query.

## Worked example: Azure Container Apps

### 1. Confirm metric names

Use a real resource:

```bash
az monitor metrics list-definitions --resource <container-app-resource-id> --query "[].{name:name.value, unit:unit, agg:primaryAggregationType}" -o table
```

Container Apps exposes, among others, `Requests`, `Replicas`, `RestartCount`, `UsageNanoCores` and `WorkingSetBytes`. Always check the names against your own tenant before relying on them.

### 2. Write the plugin

`backend/app/services/monitors/container_apps.py`:

```python
from __future__ import annotations

from app.services.monitors.base import (
    AzureResourceMonitor, ComparisonMetric, HealthRule, LogQueryDef, MetricDef, Section,
    alerts_table, bars, health_card, line, log_table, stat,
)


class ContainerAppMonitor(AzureResourceMonitor):
    key = "container_app"
    display_name = "Container App"
    category = "Containers"
    resource_types = ("microsoft.app/containerapps",)

    metrics = (
        MetricDef("requests", "Requests", "Requests", "count", "Total"),
        MetricDef("requests_by_status", "Requests", "Requests by status", "count", "Total",
                  split_by="statusCodeCategory"),
        MetricDef("replicas", "Replicas", "Replicas", "count", "Maximum"),
        MetricDef("restarts", "RestartCount", "Restarts", "count", "Total"),
        MetricDef("memory", "WorkingSetBytes", "Memory working set", "bytes", "Average"),
    )
    health_rules = (
        HealthRule("restarts", "gt", 3, 10, reducer="sum", description="Container restarts in 15 minutes"),
    )
    log_queries = (
        LogQueryDef(
            "console_logs", "Console logs",
            "ContainerAppConsoleLogs_CL\n| project TimeGenerated, RevisionName_s, Log_s\n"
            "| order by TimeGenerated desc\n| take 500",
            category="Logs",
        ),
    )
    comparison = (ComparisonMetric("requests", "sum", "Container App requests"),)
    summary_metrics = ("requests", "replicas", "restarts")

    def sections(self) -> tuple[Section, ...]:
        return (
            Section("Overview", (
                stat("requests", "Requests", "sum"),
                stat("replicas", "Replicas", "max"),
                stat("restarts", "Restarts", "sum"),
                stat("memory", "Memory"),
                bars("Requests by status", "requests_by_status", width=8),
                health_card(),
                line("Replicas", "replicas"),
                line("Memory working set", "memory"),
                alerts_table(width=12),
            )),
            Section("Logs", (log_table("console_logs", "Console logs"),)),
        )
```

The Log Analytics table name depends on how the Container Apps environment is configured, so check it in your workspace.

### 3. Register it

In `backend/app/services/monitors/registry.py`, import the class and add an instance to `_MONITORS`. Order matters only when two plugins handle the same ARM type, as Function Apps and App Services do. If the type appears in `TYPE_DISPLAY_NAMES`, remove it there.

### 4. Allow-list any properties you need

If `related()` or a `property_card` needs a property that discovery does not yet capture, add it to the `extend`/`project` clauses of `DISCOVERY_QUERY` and to `_PROPERTY_KEYS` in `backend/app/services/azure/resource_graph.py`. Capture only non-sensitive fields.

### 5. Demo data (optional)

To see the dashboard locally, add a resource to `_resources_for()` in `backend/app/services/azure/mock/estate.py`. Mock metric values come from name heuristics in `mock/services.py` (`_profile`), so new metrics get plausible values automatically.

### 6. Test it

```python
from app.services.monitors.registry import resolve_monitor, validate_all


def test_container_app_monitor() -> None:
    validate_all()
    monitor = resolve_monitor("microsoft.app/containerapps", None, None)
    assert monitor.key == "container_app"
    assert monitor.template()["sections"][0]["title"] == "Overview"
```

Then run `ruff check app tests`, `mypy app` and `pytest`.

### 7. Roll out

On the next sync after deployment, existing Container Apps resources are re-categorised (`monitor_key` changes from `generic` to `container_app`). Their dashboards are rebuilt from the new template, because the template changed and the dashboards are not customised. Health rules take effect at the next health evaluation.
