# Health, alerts and platform observability

## Resource health

Each resource has one of four states: `healthy`, `warning`, `critical` or `unknown`. Health is never invented. It is calculated in `app/services/health/evaluator.py` from these signals:

| Signal | Source | Result |
| --- | --- | --- |
| Azure Resource Health | Resource Graph `healthresources` (`availabilityState`) | `Unavailable` gives critical, `Degraded` gives warning, `Available` gives healthy |
| ARM state | Allow-listed discovery properties | A stopped App Service gives warning. SQL database status `Offline`, `Disabled`, `Suspect`, `Inaccessible`, `EmergencyMode` or `Shutdown` gives critical. `provisioningState=Failed` gives warning |
| Metric health rules | The monitor plugin's `health_rules`, evaluated through `MetricService` over each rule's window | The warning or critical threshold is breached |

The final state is the worst reason found. If there are no reasons but at least one signal was read, the resource is `healthy`. If **no signal could be read at all** (no Resource Health record, no state property, and every metric unavailable), the resource is `unknown`. Each resource stores its `health_reasons`, including the signal, severity, metric, value, threshold, operator and window, and the UI explains them on the Health tab.

Resource Health snapshots are cached per connection for `CACHE_TTL_HEALTH` seconds (default 120).

### Default thresholds

"Above" rules breach when value > threshold; "below" rules breach when value < threshold.

| Monitor | Metric | Evaluation | Direction | Warning | Critical |
| --- | --- | --- | --- | --- | --- |
| App Service / Function App | Plan CPU (`CpuPercentage`, on the App Service Plan) | avg over 15 min | above | 80 | 90 |
| App Service / Function App | Plan memory (`MemoryPercentage`, on the plan) | avg over 15 min | above | 85 | 95 |
| App Service / Function App | HTTP 5xx (`Http5xx`) | sum over 15 min | above | 10 | 50 |
| App Service / Function App | Response time (`HttpResponseTime`, ms) | avg over 15 min | above | 1000 | 3000 |
| App Service / Function App | Health check status (`HealthCheckStatus`) | avg over 15 min | below | 95 | 80 |
| App Service Plan | CPU / Memory | avg over 15 min | above | 80 / 85 | 90 / 95 |
| Azure SQL Database | CPU (`cpu_percent`) | avg over 15 min | above | 80 | 90 |
| Azure SQL Database | DTU (`dtu_consumption_percent`) | avg over 15 min | above | 85 | 95 |
| Azure SQL Database | Storage used (`storage_percent`) | max over 15 min | above | 85 | 95 |
| Azure SQL Database | Log IO (`log_write_percent`) | avg over 15 min | above | 85 | 95 |
| Azure SQL Database | Deadlocks (`deadlock`) | sum over 15 min | above | 5 | 20 |
| Azure SQL Database | Failed connections, system (`connection_failed`) | sum over 15 min | above | 10 | 50 |
| Azure SQL Database | Availability (`availability`) | avg over 60 min | below | 99.9 | 99.0 |
| SQL Elastic Pool | CPU / Storage used | avg / max over 15 min | above | 80 / 85 | 90 / 95 |
| Azure Front Door | 5xx rate (`Percentage5XX`) | avg over 15 min | above | 1 | 5 |
| Azure Front Door | Origin health (`OriginHealthPercentage`) | avg over 15 min | below | 90 | 50 |
| Azure Front Door / classic | Total latency (`TotalLatency`, ms) | avg over 15 min | above | 1000 | 3000 |
| Azure Front Door (classic) | Backend health (`BackendHealthPercentage`) | avg over 15 min | below | 90 | 50 |
| Application Insights | Availability tests | avg over 30 min | below | 99 | 95 |
| Application Insights | Failed requests | sum over 15 min | above | 20 | 100 |
| Application Insights | Server response time (ms) | avg over 15 min | above | 1000 | 3000 |
| Storage Account / Key Vault | Availability | avg over 60 min | below | 99.9 | 99.0 |
| Key Vault | Saturation (`SaturationShoebox`) | avg over 15 min | above | 75 | 90 |
| Cosmos DB | Normalised RU consumption | max over 15 min | above | 80 | 95 |
| Cosmos DB | Availability (`ServiceAvailability`) | avg over 60 min | below | 99.9 | 99.0 |
| Azure Cache for Redis | Server load / Memory used | max over 15 min | above | 80 | 95 |
| Virtual Machine | CPU (`Percentage CPU`) | avg over 15 min | above | 80 | 90 |
| Virtual Machine | VM availability (`VmAvailabilityMetric`, shown as %) | avg over 15 min | below | 100 | 50 |
| Kubernetes Service | Node CPU / Node memory | avg over 15 min | above | 80 / 85 | 90 / 95 |
| Service Bus | Dead-lettered messages | max over 15 min | above | 10 | 1000 |
| Service Bus / Event Hubs | Server errors | sum over 15 min | above | 10 | 50 |
| Event Hubs | Throttled requests | sum over 15 min | above | 10 | 100 |
| Application Gateway | Unhealthy hosts | max over 15 min | above | 0 | 1 |
| Application Gateway | Failed requests | sum over 15 min | above | 10 | 100 |
| Load Balancer | Data path availability / Health probe status | avg over 15 min | below | 99 / 90 | 90 / 50 |
| Public IP Address | Under DDoS attack | max over 15 min | above | - | 0 |

Container Registry and Azure SQL Server have no metric health rules. Their health comes from Resource Health and state.

### Overriding thresholds

`GET /api/v1/health-rules` lists every rule with its default and effective thresholds. `PUT /api/v1/health-rules` (permission `settings:manage`, which in practice means Super Admin) stores an organisation override in `health_thresholds` for a `(monitor_key, metric_name)` pair: warning, critical, and enabled. Disabled rules are skipped. Overrides apply at the next evaluation. `POST /api/v1/resources/{id}/health/evaluate` (Operator and above) re-evaluates one resource immediately.

Gauges and metric cards receive the plugin's **default** thresholds in their widget configuration, so the UI can colour values. Organisation overrides affect health evaluation but are not written into widget configuration.

## Alerts

Alert rules (`/api/v1/alert-rules`, permission `alerts:manage`) target one monitor type and one plugin metric. They can be narrowed to a project, an environment or a single resource, and they define:

- an aggregation: Average, Total, Maximum, Minimum or Count
- an operator (`gt`, `gte`, `lt`, `lte`) and a threshold
- a severity: critical, warning or info
- a window of 5 to 1,440 minutes
- notification channels

Rules are evaluated with health, every `HEALTH_INTERVAL_MINUTES`:

| Situation | Action |
| --- | --- |
| Breach and no open alert with the same fingerprint (`rule:<rule_id>:<resource_id>`) | Create an `active` alert, add a `fired` event, and notify |
| Breach and an open (`active` or `acknowledged`) alert exists | Update the current value and evaluation time only. There is no duplicate alert and no repeat notification |
| No breach and an open alert exists | Set it to `resolved`, add a `resolved` event, and notify |
| No data | Leave the alert unchanged |

Users with `alerts:acknowledge` (Operator and above) can acknowledge an active alert or resolve an alert manually. Every transition is recorded in `alert_events`, and is also audited when a user performs it. Alerts show project, environment, resource, severity, metric, unit, current value, threshold, start time and status.

Only platform-evaluated rules are supported. Alerts defined in Azure Monitor itself are not imported yet (see [roadmap.md](roadmap.md)).

## Notification channels

| Type | Status | Delivery |
| --- | --- | --- |
| `webhook` | Implemented | JSON POST (`summary` plus alert fields) |
| `teams` | Implemented | Adaptive Card POST to a Teams Workflows or incoming-webhook URL |
| `slack` | Implemented | `{"text": ...}` POST to a Slack incoming webhook |
| `email` | Placeholder | Always fails with "Email delivery is not configured in this deployment." |

Endpoint URLs are secrets and are **not stored in the database**. A channel holds `secret_ref`, the name of a Key Vault secret whose value is the HTTPS URL. The URL is read with the managed identity at send time. Channel settings that look like URLs are rejected, and non-HTTPS endpoints are refused. The platform Key Vault is shared by every organisation, so **a channel's secret name must start with the organisation's slug and a hyphen**, for example `contoso-teams-ops` for the organisation `contoso`; other names are rejected when the channel is created. Delivery is refused for endpoints that resolve to loopback, private, link-local, reserved or multicast addresses. The channel test reports one generic failure message whatever went wrong (missing secret, non-HTTPS URL, refused address or HTTP error), so it cannot be used to probe Key Vault; the specific reason is in the API logs.

In development without Key Vault, the secret can come from an environment variable `SECRET_<NAME>`, for example `SECRET_CONTOSO_TEAMS_OPS` for `contoso-teams-ops`. That fallback is disabled outside development and test.

Delivery failures never stop evaluation. They are recorded as `notification_failed` events. `POST /api/v1/notification-channels/{id}/test` sends a test message.

New channel types implement `NotificationSender` (`app/services/alerts/channels/base.py`) and are registered in `channels/registry.py`.

## Synchronisation and scheduling

| Setting | Default | Meaning |
| --- | --- | --- |
| `SYNC_INTERVAL_MINUTES` | 15 | Beat queues a scheduled sync for every enabled connection without a run in flight |
| `HEALTH_INTERVAL_MINUTES` | 5 | Beat runs health evaluation followed by alert rule evaluation for every organisation |
| `TASK_BACKEND` | `celery` | `inline` is for development and test only |

Sync upserts by ARM resource ID, updates metadata and tags, re-applies tag mapping (except manual assignments), marks resources missing from Azure as deleted, restores them if they reappear, and rebuilds dashboards whose template changed.

## Caching

| Data | TTL | Key |
| --- | --- | --- |
| Metric series | `CACHE_TTL_METRICS` = 60 s | tenant, resource, metric, aggregation, namespace, split, start, end, interval |
| Resource Health snapshot | `CACHE_TTL_HEALTH` = 120 s | tenant and subscriptions |
| Service Health and recent changes (overview) | 300 s | tenant and subscriptions |
| Per-resource change history | 300 s | tenant and subscription |

Preset time ranges end on the current minute, so cache keys are stable within a minute. The cache is Redis when `REDIS_URL` is set, and in-process otherwise. Cache failures are logged and never fail a request. Tokens and secrets are never cached. `CACHE_TTL_RESOURCE_GRAPH` is defined in configuration but not currently used, because discovery always reads live.

## Observability of the platform itself

| Endpoint | Purpose |
| --- | --- |
| `GET /live` | Liveness. The process is up |
| `GET /ready` | Readiness. Database `SELECT 1` (with latency) and Redis ping when configured. Returns 503 if degraded |
| `GET /health` | Readiness checks plus environment, Azure provider and uptime |
| `GET /metrics` | Prometheus text format. **Restrict it at the ingress**; it is unauthenticated |

These probes are served by the API container only; the public nginx front end proxies `/api` alone, so they are not reachable from the internet.

Metrics from `app/core/metrics.py`, counted per process:

| Metric | Labels |
| --- | --- |
| `amp_http_requests_total` | `status` (2xx, 4xx, ...) |
| `amp_http_request_duration_seconds` (histogram) | `route` (UUIDs normalised to `{id}`) |
| `amp_azure_calls_total`, `amp_azure_failures_total` | `operation` (for example `resource_graph.query`, `metrics.query`, `logs.query_resource`) |
| `amp_job_runs_total`, `amp_job_failures_total` | `job` (`sync`, `health`) |
| `amp_sync_failures_total` | `code` (error code) |

Logs are single-line JSON on stdout, carrying `timestamp`, `level`, `logger`, `request_id` and `user_id`. An `http_request` access log is written with method, route, status and duration (liveness, readiness and metrics are excluded). Bearer tokens, JWTs and secret-bearing query parameters are redacted, and Azure SDK HTTP logging is kept at WARNING.

Each response carries `X-Request-ID`. An incoming value is reused if it matches `[A-Za-z0-9._-]{8,64}`; otherwise a new ID is generated. Error bodies include the same `request_id`.

In the Azure deployment, Container Apps stream these logs to the Log Analytics workspace created for the platform (see [deployment.md](deployment.md)).
