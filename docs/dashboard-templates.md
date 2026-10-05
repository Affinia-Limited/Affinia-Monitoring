# Dashboard templates

Dashboards are generated, not hand-built. Every discovered resource is matched to a monitor plugin (`app/services/monitors/`). The plugin's template is stored in `dashboard_templates`, and a dashboard with widgets is created for the resource.

```text
resource_type + kind + sku  --resolve_monitor()-->  monitor plugin  --template()-->  dashboard_templates
                                                                                         |
discovered resource  ----------------------------------------generate_dashboards()-->  dashboards + dashboard_widgets
```

## Resolution

`resolve_monitor()` checks the plugins in registry order and returns the first whose `matches()` is true. Otherwise it returns the `generic` monitor, which provides an overview, health and alerts only.

| Monitor | Key | ARM type | Matching detail | Dashboard sections |
| --- | --- | --- | --- | --- |
| App Service | `app_service` | `microsoft.web/sites` | kind not containing `functionapp` | Overview, HTTP, Resources, Application Insights, Logs |
| Function App | `function_app` | `microsoft.web/sites` | kind contains `functionapp` | Overview, Application Insights, Logs |
| App Service Plan | `app_service_plan` | `microsoft.web/serverfarms` | | Overview |
| Azure SQL Database | `sql_database` | `microsoft.sql/servers/databases` | excludes SKU `System` (`master`) | Overview, Connections, Storage, Query performance, Diagnostics |
| Azure SQL Server | `sql_server` | `microsoft.sql/servers` | | Overview (databases table) |
| SQL Elastic Pool | `sql_elastic_pool` | `microsoft.sql/servers/elasticpools` | | Overview |
| Azure Front Door | `front_door` | `microsoft.cdn/profiles` | SKU contains `AzureFrontDoor` (Standard/Premium) | Overview, Origins, Traffic, Security |
| Azure Front Door (classic) | `front_door_classic` | `microsoft.network/frontdoors` | | Overview |
| Application Insights | `app_insights` | `microsoft.insights/components` | | Application, Performance, Failures, Dependencies, Availability, Logs |
| Storage Account | `storage_account` | `microsoft.storage/storageaccounts` | | Overview |
| Key Vault | `key_vault` | `microsoft.keyvault/vaults` | | Overview |
| Container Registry | `container_registry` | `microsoft.containerregistry/registries` | | Overview |
| Cosmos DB | `cosmos_db` | `microsoft.documentdb/databaseaccounts` | | Overview |
| Azure Cache for Redis | `redis` | `microsoft.cache/redis` | | Overview |
| Virtual Machine | `virtual_machine` | `microsoft.compute/virtualmachines` | | Overview |
| Kubernetes Service | `aks` | `microsoft.containerservice/managedclusters` | | Overview |
| Service Bus | `service_bus` | `microsoft.servicebus/namespaces` | | Overview |
| Event Hubs | `event_hubs` | `microsoft.eventhub/namespaces` | | Overview |
| Application Gateway | `application_gateway` | `microsoft.network/applicationgateways` | | Overview |
| Load Balancer | `load_balancer` | `microsoft.network/loadbalancers` | | Overview |
| Public IP Address | `public_ip` | `microsoft.network/publicipaddresses` | | Overview |
| Azure resource | `generic` | anything else (VNets, NICs, workspaces, ...) | fallback | Overview |

Microsoft CDN profiles (classic CDN SKUs) resolve to `generic`. Sections map to tabs on the resource page. The UI adds fixed tabs for Health, Alerts, Configuration (properties), Tags and Activity.

## Widget types

Configuration keys are stored in `dashboard_widgets.config`. Metric references are plugin **metric keys** (for example `plan_cpu`), not Azure metric names.

| `widget_type` | Config keys | Data source |
| --- | --- | --- |
| `metric_card` | `metric`, `reducer` (`avg`, `sum`, `max`, `min`), optional `thresholds` | `GET /resources/{id}/metrics` |
| `gauge` | `metric`, `reducer`, `max` (default 100), optional `thresholds` | metrics |
| `line_chart` | `metrics` (list), `stacked` | metrics |
| `area_chart` | `metrics`, `stacked` (default true) | metrics |
| `bar_chart` | `metrics`, `stacked` (default true). Split metrics render one series per dimension value | metrics |
| `resource_health` | none | resource health fields |
| `alert_table` | none | `GET /alerts?resource_id=...` |
| `log_table` | `query` (predefined query key) | `POST /logs/query` |
| `log_chart` | `query` (a `timechart` query) | `POST /logs/query` |
| `dependency_map` | `query` (Source/Target edge query) | `POST /logs/query` |
| `resource_table` | `relation`: `children`, `apps_on_plan`, `app_service_plan`, `app_insights` | `GET /resources/{id}/related/{relation}` |
| `property_card` | `property` (an allow-listed discovery property), `label`, optional `format` (`bytes`) | resource properties |
| `app_insights_status` | `relation` (`app_insights`) | resource detail `related` map |

`thresholds` is added automatically to single-metric widgets whose metric has a health rule: `{"operator": "gt" or "lt", "warning": n, "critical": n}`. These are the plugin defaults and do not include organisation overrides. Widgets without thresholds use a neutral colour. Every widget has `title`, `width` (1 to 12 on a 12-column grid), `section` and `position`.

## Related-resource metrics

A metric definition can target a related resource: `MetricDef(..., target="related:app_service_plan")`. The monitor's `related()` method maps relation names to ARM IDs from discovery properties. App Service uses `serverFarmId` for the plan and `appInsightsResourceId` for the linked component. The related resource must itself be discovered in the same organisation; otherwise the metric returns `unavailable_reason: RELATED_RESOURCE_NOT_FOUND`. This is how an App Service dashboard shows plan CPU and memory, which Azure reports on the plan rather than the site.

Log queries use the same mechanism. For example, the App Service "Recent exceptions" query targets `related:app_insights` and runs against the component.

## Log query definitions

```python
LogQueryDef(
    key="app_logs",
    title="Application logs",
    kql="AppServiceAppLogs\n| project TimeGenerated, Level, Host, ResultDescription\n| order by TimeGenerated desc\n| take 500",
    severity_column="Level",   # enables the severity filter in the Logs page
    visualization="table",     # or "timechart"
    target="self",             # or "related:<relation>"
    category="Application",
)
```

The time range is passed to Azure as the query timespan, so KQL does not need a `TimeGenerated` filter. Search and severity filters are appended safely by `apply_filters()`, which quotes the values as KQL string literals.

## Versioning and customisation

- `sync_templates()` runs at start-up and during every sync. If a plugin's template definition changes, or its `template_version` is raised, the stored template `version` is incremented. Stored versions only ever move forward.
- `generate_dashboards()` rebuilds a dashboard's widgets when its `template_version` is older than the template's, **unless the dashboard is customised**.
- `PATCH /api/v1/dashboards/{id}` (permission `dashboards:manage`) replaces the widget list. Metric and query references are validated against the resource's monitor, and the dashboard is marked `is_customized`, so template upgrades no longer overwrite it.
- `POST /api/v1/dashboards/{id}/reset` rebuilds the dashboard from its current template and clears `is_customized`.
- When a resource disappears from Azure, its dashboard is archived (soft-deleted). It is restored if the resource reappears.

In the UI, customised dashboards show a "Customised" badge, and the dashboard page offers "Reset to template". Users with `dashboards:manage` can enter Customise mode to remove widgets, change widths, reorder widgets within a section and add line charts from the resource's metric catalogue (`GET /resources/{id}/metric-definitions`); saving sends the full widget list to `PATCH /dashboards/{id}`, which validates every metric and log-query reference.

`GET /api/v1/dashboards/templates` lists stored templates and their definitions.
