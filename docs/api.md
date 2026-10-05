# REST API reference

Base path: `/api/v1`. All endpoints except `GET /auth/config` require `Authorization: Bearer <Entra access token>`. In `AUTH_MODE=dev` (development only) no token is needed. Interactive OpenAPI documentation is served at `/api/docs` outside production.

Permissions are enforced server-side. A missing permission returns `403 PERMISSION_DENIED` and is recorded in the audit log as `authorization.denied`.

## Roles and permissions

| Permission | Viewer | Operator | Admin | Super Admin |
| --- | :-: | :-: | :-: | :-: |
| `dashboards:view` | Yes | Yes | Yes | Yes |
| `resources:view` | Yes | Yes | Yes | Yes |
| `alerts:view` | Yes | Yes | Yes | Yes |
| `logs:view` | | Yes | Yes | Yes |
| `logs:run_kql` | | Yes | Yes | Yes |
| `alerts:acknowledge` | | Yes | Yes | Yes |
| `azure:sync` | | Yes | Yes | Yes |
| `dashboards:manage` | | | Yes | Yes |
| `azure:connect` | | | Yes | Yes |
| `projects:manage` | | | Yes | Yes |
| `alerts:manage` | | | Yes | Yes |
| `audit:view` | | | Yes | Yes |
| `users:manage` | | | | Yes |
| `settings:manage` | | | | Yes |

## Errors

```json
{"error": {"code": "AZURE_PERMISSION_DENIED", "message": "The connected identity does not have permission to read this resource.", "request_id": "...", "details": {}}}
```

| Status | Typical codes |
| --- | --- |
| 401 | `UNAUTHENTICATED`, `TOKEN_EXPIRED` |
| 403 | `ACCESS_NOT_GRANTED` (authenticated but not an active member; deliberately generic), `ACCESS_SUSPENDED`, `PERMISSION_DENIED`, `AZURE_PERMISSION_DENIED` |
| 404 | `NOT_FOUND`, `METRIC_NOT_FOUND`, `QUERY_NOT_FOUND`, `RELATED_RESOURCE_NOT_FOUND`, `AZURE_NOT_FOUND` |
| 409 | `CONFLICT`, `USER_EXISTS`, `LAST_SUPER_ADMIN`, `INVALID_STATUS`, `PROJECT_EXISTS`, `ENVIRONMENT_EXISTS`, `SUBSCRIPTION_ALREADY_CONNECTED` |
| 422 | `VALIDATION_FAILED` (field locations only, submitted values are never echoed), `SELF_MODIFICATION`, `ROLE_MANAGED_BY_ENTRA`, `KQL_FORBIDDEN`, `KQL_EMPTY`, `KQL_TOO_LONG` |
| 429 | `RATE_LIMITED` |
| 400 | `AZURE_QUERY_ERROR` |
| 502 / 503 | `AZURE_ERROR`, `AZURE_UNREACHABLE`, `AZURE_AUTHENTICATION_FAILED`, `AZURE_THROTTLED` |
| 500 | `INTERNAL_ERROR`, with no internal detail |

Time-range parameters: `timeRange` = `30m`, `1h`, `6h`, `24h`, `7d`, `30d` or `custom`. For `custom`, also pass ISO 8601 `start` and `end`. The end must be after the start, and custom ranges are limited to 93 days.

## Auth

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/auth/config` | public | Non-secret MSAL settings |
| GET | `/auth/me` | active member | User, organisation, role, permissions, auth mode, Azure provider. `403 ACCESS_NOT_GRANTED` or `ACCESS_SUSPENDED` if the caller is not an active member |
| POST | `/auth/session` | active member | Records `user.login_allowed` and updates the last login time |

## Overview and search

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/overview` | `dashboards:view` | Totals, resource health counts, `environment_health` (environments by worst status), alerts, per-project and per-environment health with `active_alerts` and `last_checked_at`, recent alerts, resource types, Service Health, recent changes, feed errors, `generated_at` and `last_synced_at` |
| GET | `/search?q=&limit=` | `resources:view` | Projects, environments, resources (name, resource group, type, region, friendly type names), open alerts, log shortcuts and subscriptions. Compound terms such as `crm-prod` match a project plus its environment. Every hit carries `project_name`, `environment_name` and `type_display_name` where relevant |

## Projects

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/projects` | `resources:view`. Health counts cover monitored resources only; each environment includes `active_alerts` and `last_checked_at` |
| POST | `/projects` | `projects:manage` |
| GET | `/projects/{id}` | `resources:view` |
| PATCH | `/projects/{id}` | `projects:manage` |
| DELETE | `/projects/{id}` | `projects:manage` (soft delete; resources are unassigned) |
| POST | `/projects/{id}/environments` | `projects:manage` |
| PATCH | `/projects/{id}/environments/{env_id}` | `projects:manage` |
| DELETE | `/projects/{id}/environments/{env_id}` | `projects:manage` |
| GET | `/projects/{id}/comparison?timeRange=` | `dashboards:view` |

## Azure connections

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/azure/identity` | `azure:connect` | Platform identity client ID, home tenant and required roles. No secrets |
| GET | `/azure/available-subscriptions?tenant_id=` | `azure:connect` | Subscriptions the identity can read |
| GET | `/azure/connections` | `resources:view` | |
| POST | `/azure/connections` | `azure:connect` | `202 Accepted`. Returns the connection and a queued sync run |
| GET | `/azure/connections/{id}` | `resources:view` | |
| PATCH | `/azure/connections/{id}` | `azure:connect` | Name, `sync_enabled`, defaults, `add_subscription_ids` |
| DELETE | `/azure/connections/{id}` | `azure:connect` | Disconnect. Resources and dashboards are archived |
| POST | `/azure/connections/{id}/sync` | `azure:sync` | Returns the in-flight run if one exists |
| POST | `/azure/sync` | `azure:sync` | All connections in the organisation |
| GET | `/azure/sync-runs/{run_id}` | `resources:view` | Step-by-step progress |
| GET | `/azure/connections/{id}/sync-runs` | `resources:view` | Last 20 runs |
| GET | `/azure/subscriptions` | `resources:view` | |

## Resources

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/resources` | `resources:view` | Filters: `project_id`, `environment_id`, `subscription_id`, `resource_group`, `resource_type`, `monitor_key` (comma-separated), `location`, `health` (comma-separated), `q`, `unassigned`, `monitored_only`. Each item includes `health_metrics` (latest reading of every health-rule metric from the last evaluation) and `active_alerts`. Also `page`, `page_size` (up to 500) and `sort` (`name`, `type`, `health`, `location`, `last_seen`, prefix `-` for descending) |
| GET | `/resources/facets` | `resources:view` | Counts by type, location, resource group, subscription and health (accepts the same filters, plus `monitored_only`) |
| GET | `/resources/monitors` | `resources:view` | Supported monitors and their non-split metrics |
| GET | `/resources/{id}` | `resources:view` | Detail, including allow-listed properties, related IDs and Azure portal URL |
| GET | `/resources/{id}/metric-definitions` | `resources:view` | |
| GET | `/resources/{id}/metrics?metrics=a,b&timeRange=` | `dashboards:view` | Between 1 and 20 metric keys |
| GET | `/resources/{id}/related/{relation}` | `resources:view` | `children`, `apps_on_plan`, `app_service_plan`, `app_insights` |
| PUT | `/resources/{id}/assignment` | `projects:manage` | Manual project/environment assignment, pinned across syncs |
| POST | `/resources/{id}/health/evaluate` | `azure:sync` | Re-evaluate now (this calls Azure) |
| GET | `/resources/{id}/activity` | `resources:view` | Resource Graph change history (last 7 days) |

## Dashboards

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/dashboards?project_id=&environment_id=&monitor_key=&include_generic=` | `dashboards:view` |
| GET | `/dashboards/templates` | `dashboards:view` |
| GET | `/dashboards/by-resource/{resource_id}` | `dashboards:view` |
| GET | `/dashboards/{id}` | `dashboards:view` |
| PATCH | `/dashboards/{id}` | `dashboards:manage` |
| POST | `/dashboards/{id}/reset` | `dashboards:manage` |

## Logs

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/logs/targets` | `logs:view` | Resources with predefined queries, including Log Analytics workspaces, with project and environment IDs and names |
| GET | `/logs/queries?resource_id=` | `logs:view` | Predefined queries for the target |
| POST | `/logs/query` | `logs:view`; free-form `kql` also needs `logs:run_kql` | Body: `resource_id`, `query_key` or `kql`, `time_range`, optional `start`/`end`, `search`, `severities` |

## Alerts, rules, channels and health rules

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/alerts?status=active\|acknowledged\|resolved\|open&severity=&project_id=&environment_id=&resource_id=&q=&monitor_key=&since_hours=` | `alerts:view`. `q` searches the alert title and resource name, `monitor_key` filters by resource type, `since_hours` (1 to 2160) by start time |
| GET | `/alerts/{id}` | `alerts:view` (includes events) |
| POST | `/alerts/{id}/acknowledge` | `alerts:acknowledge` |
| POST | `/alerts/{id}/resolve` | `alerts:acknowledge` |
| GET | `/alert-rules` | `alerts:view` |
| POST | `/alert-rules` | `alerts:manage` |
| PUT | `/alert-rules/{id}` | `alerts:manage` |
| DELETE | `/alert-rules/{id}` | `alerts:manage` |
| GET | `/notification-channels` | `alerts:manage` |
| POST | `/notification-channels` | `alerts:manage` |
| DELETE | `/notification-channels/{id}` | `alerts:manage` |
| POST | `/notification-channels/{id}/test` | `alerts:manage` |
| GET | `/health-rules` | `alerts:view` |
| PUT | `/health-rules` | `settings:manage` |

Alerts are created by the evaluator from alert rules. There is no endpoint to create an alert directly; `POST /alert-rules` creates the rule.

## Users and audit

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/roles` | `dashboards:view` |
| GET | `/users?q=&role=&status=&page=&page_size=` | `users:manage`. Paged (max 100). `q` searches name and email |
| POST | `/users/invite` | `users:manage`. Body `{email, role_key, display_name?}`. Creates or refreshes a pending invitation (30 days) |
| GET | `/users/{id}` | `users:manage`. Includes `entra_object_id` and `entra_tenant_id` |
| PATCH | `/users/{id}` | `users:manage`. Body `{role_key?, display_name?}` |
| POST | `/users/{id}/suspend` | `users:manage`. Active users only; takes effect on the user's next request |
| POST | `/users/{id}/reactivate` | `users:manage`. Suspended or deactivated becomes active; an unredeemed revoked invitation becomes pending |
| POST | `/users/{id}/deactivate` | `users:manage`. Removes access or revokes an invitation. The row and history are kept |
| GET | `/users/{id}/audit?page=&page_size=` | `users:manage`. Audit entries about or by the user |

All user changes enforce: no self-modification, no role above your own, no managing a higher-ranked user, at least one active Super Admin, and no edits to Entra-managed roles. Users are never deleted.
| GET | `/audit-logs?action=&result=&page=&page_size=` | `audit:view` |

## Platform endpoints (outside `/api/v1`, unauthenticated)

`GET /live`, `GET /ready`, `GET /health`, `GET /metrics`. See [monitoring.md](monitoring.md#observability-of-the-platform-itself).
