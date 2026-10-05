# Troubleshooting

Every API error includes `request_id`. Search the JSON logs for it (`"request_id": "<id>"`) to find the server-side context.

## Sign-in and API access

| Symptom / code | Likely cause | Fix |
| --- | --- | --- |
| `401 UNAUTHENTICATED` "Authentication is required." | No bearer token (the SPA is in `dev` mode against an `entra` backend, or the reverse) | Align `VITE_AUTH_MODE` with the backend `AUTH_MODE` |
| `401` "Sign-in from this tenant is not permitted." | The token's `tid` is not `ENTRA_TENANT_ID` or in `ENTRA_ALLOWED_TENANTS` | Add the tenant, or sign in with the home tenant |
| `401` "The access token issuer is not trusted." | A v1.0 token (`sts.windows.net` issuer) | Set `accessTokenAcceptedVersion: 2` on the API app registration |
| `401` "The access token was not issued for this API." | `aud` differs from `ENTRA_AUDIENCE` | Use the Application ID URI (or client ID) that appears in the token's `aud` |
| `401 TOKEN_EXPIRED` | The token lifetime has passed (60 s leeway) | The SPA renews silently. Check clock skew on the server |
| `401` "Unable to validate the access token at this time." | The JWKS endpoint is unreachable | Allow outbound HTTPS to `login.microsoftonline.com` |
| `403 PERMISSION_DENIED` "does not grant access to this API" | The token has neither `access_as_user` in `scp` nor app roles | Request the scope `api://<api>/access_as_user` (`VITE_ENTRA_API_SCOPE`) and grant consent |
| `403 PERMISSION_DENIED` on an action | The role lacks the permission ([api.md](api.md#roles-and-permissions)) | Assign an Entra app role, or change the role under Settings, Users |
| Role reverts to Viewer | Entra app roles were removed, and roles are Entra-managed | Reassign the app role in Enterprise applications |
| "Access not granted" (`403 ACCESS_NOT_GRANTED`) after signing in | The user has not been added, the invitation expired or was revoked, or the user is deactivated | Add or reactivate the user under Settings > Users. See [user-access-management.md](user-access-management.md#11-troubleshooting) |
| "Access suspended" (`403 ACCESS_SUSPENDED`) | The user was suspended | Reactivate under Settings > Users |
| `409 LAST_SUPER_ADMIN` | Attempt to demote or remove the only active Super Admin | Promote another user first |
| `429 RATE_LIMITED` | Over `RATE_LIMIT_PER_MINUTE`, or `RATE_LIMIT_KQL_PER_MINUTE` for custom KQL | Wait a minute, or tune the limits |
| Application refuses to start: "AUTH_MODE=dev is only permitted..." | A development mode with `ENVIRONMENT=staging` or `production` | Use `AUTH_MODE=entra`, `AZURE_PROVIDER=azure` and `TASK_BACKEND=celery` |
| "AUTH_MODE=entra requires: ENTRA_TENANT_ID, ..." | Missing Entra settings | Set `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` and `ENTRA_AUDIENCE` |
| Error parsing a list setting | Malformed value | List settings accept comma-separated values or a JSON array |

## Azure connection and sync

The sync run records the first failing step. Later steps show `skipped`, and the connection shows `last_error_code`.

| Failed step / code | Cause | Fix |
| --- | --- | --- |
| Authenticate / `AZURE_AUTHENTICATION_FAILED` | No usable identity (managed identity not assigned, wrong `AZURE_CLIENT_ID`, or no `az login` in development) | Assign the user-assigned identity to the app and set `AZURE_CLIENT_ID`. Locally, run `az login --tenant <tenant>` |
| Verify subscriptions / `AZURE_PERMISSION_DENIED` or `AZURE_NOT_FOUND` | No read access at subscription scope, a wrong subscription ID, or the wrong tenant | Grant Reader on the subscription. Check the tenant (Lighthouse or `AZURE_ADDITIONALLY_ALLOWED_TENANTS` for other tenants) |
| Verify read permissions / `AZURE_PERMISSION_DENIED` | Resource Graph read denied | Grant Reader |
| Discover / `AZURE_THROTTLED` | Resource Graph throttling | Retry later, or raise `SYNC_INTERVAL_MINUTES` |
| `SUBSCRIPTION_ALREADY_CONNECTED` | The subscription belongs to another connection in the organisation | Edit that connection, or disconnect it first |
| A run stays "queued" | No worker consuming the queue (`TASK_BACKEND=celery` without a running worker or Redis) | Start the worker and Redis. Runs older than one hour are marked `STALE` and a new one can be started |
| Resources show no project | Tags do not match any project slug, name or `tag_values`, and no default is set | Add tag values to the project, set connection defaults, or assign manually |
| A removed resource is still listed | No sync has run since the removal | Sync now. Missing resources are then marked deleted |

## Metrics, dashboards and logs

| Symptom / code | Cause | Fix |
| --- | --- | --- |
| Widget shows "Not available" with `NO_DATA` | Azure returned no series (for example DTU on a vCore database, or an idle resource) | Expected. The metric does not apply, or there is no traffic |
| `RELATED_RESOURCE_NOT_FOUND` on App Service plan metrics or App Insights queries | The App Service Plan or Application Insights component is in a subscription that is not connected, or there is no `hidden-link` tag | Connect that subscription, or link Application Insights to the app |
| `AZURE_PERMISSION_DENIED` on a metric | Monitoring Reader is missing at that scope | Grant Monitoring Reader |
| `METRIC_NOT_FOUND` | A widget or rule references a key that the resource's monitor does not define | Use a key from `GET /resources/{id}/metric-definitions` |
| Log tables empty | No diagnostic settings, or diagnostics sent elsewhere | Configure diagnostic settings to a Log Analytics workspace ([azure-setup.md](azure-setup.md)) |
| `AZURE_QUERY_ERROR` | KQL syntax error or unknown table, reported by Azure | Correct the query. The message shown comes from Azure |
| `KQL_FORBIDDEN` | The query uses `workspace()`, `app()`, a management command, `externaldata` or a blocked `evaluate` plugin | Queries are scoped to the selected resource. Pick the workspace or resource as the target instead |
| Result truncated | Over `LOG_QUERY_MAX_ROWS` (5,000) | Add `summarize` or `take`, or narrow the time range |
| Front Door dashboard is generic | The profile is a classic CDN SKU (`Standard_Microsoft` and similar), which is not Front Door | Expected. Only `Standard_AzureFrontDoor` and `Premium_AzureFrontDoor` use the Front Door monitor. Classic Front Door (`microsoft.network/frontdoors`) has its own, smaller monitor |
| Dashboard did not pick up a template change | The dashboard is customised | Use Reset to template (`POST /dashboards/{id}/reset`) |
| Health stays "unknown" | No signal readable: no Resource Health record, no state, all metrics unavailable | Check Reader and Monitoring Reader grants |

## Start-up and infrastructure

| Symptom | Cause | Fix |
| --- | --- | --- |
| Log `template_sync_skipped` at start-up | The database is not migrated yet | Run `alembic upgrade head`. Templates are also synchronised during every sync |
| `/ready` returns 503 with `database: error` | The database is unreachable, or Entra token login failed (`DATABASE_AUTH=entra`) | Check networking and the managed identity's PostgreSQL role |
| `/ready` shows `redis: error` | Redis is unreachable | Check `REDIS_URL` and the private endpoint |
| UI "Demo data" badge in a real deployment | `AZURE_PROVIDER=mock` | This cannot happen in staging or production: configuration validation refuses it |
