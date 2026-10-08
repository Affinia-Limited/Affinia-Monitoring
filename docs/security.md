# Security

## Threat model summary

| Asset | Threat | Primary controls |
| --- | --- | --- |
| Read access to customer Azure estates | Credential theft, over-privileged identity | No stored credentials; managed/workload identity; read-only RBAC only |
| Monitoring data (metrics, logs) | Cross-organisation or cross-resource disclosure | Organisation scoping on every query; a subscription belongs to one organisation, and only to one approved for its home tenant; resource-centric log queries; KQL guard |
| The API | Forged or replayed tokens, privilege escalation | Full Entra token validation; server-side RBAC; no self or upward role changes |
| Notification endpoints | Leaking webhook URLs | Key Vault secret references only |
| Logs and audit trail | Token or secret leakage | Redaction; sanitised audit details |
| Availability | Abuse, expensive queries | Per-user rate limits, stricter KQL limit, row caps, WAF |

## Implemented controls

### Credentials and secrets

- **No Azure credentials are stored**, in PostgreSQL or anywhere else. `azure_connections` holds the tenant ID, subscription IDs and settings. Extra fields such as `client_secret` in a request are ignored, and this is covered by a test.
- The platform authenticates with `DefaultAzureCredential` (Managed Identity or Workload Identity). `EnvironmentCredential` (service principal secrets), interactive browser, shared token cache and VS Code credentials are excluded. Developer credentials (Azure CLI and similar) are enabled only when `ENVIRONMENT=development`.
- Secrets that are unavoidable, such as webhook URLs and the Redis URL in Azure, live in **Key Vault**. The database stores only a secret name (`secret_ref`). Channel settings containing URLs are rejected.
- PostgreSQL in Azure uses **Microsoft Entra authentication** (`DATABASE_AUTH=entra`). The managed identity's access token is supplied as the connection password for each new connection, and pooled connections recycle every 30 minutes. Password authentication is disabled on the server by the Bicep.
- There are no secrets in source control. `.env` is git-ignored, `.env.example` holds placeholders only, and CI runs Gitleaks.
- The frontend never receives Azure credentials. It holds only an Entra access token for the API, cached in `sessionStorage` by MSAL.

### Authentication and authorisation

- Entra access tokens are fully validated (RS256 signature against the tenant JWKS, issuer, audience, `exp`/`nbf`/`iat`, tenant allow-list, required scope or app role). See [entra-id.md](entra-id.md). Tokens are never logged, stored or returned.
- **Admin-controlled membership.** A valid Entra token proves identity only. Every protected request must also map to an approved user with status `active`, looked up by the immutable `(organisation, tid, oid)`. Unknown, pending (unredeemed), suspended and deactivated users get `403 ACCESS_NOT_GRANTED` (or `ACCESS_SUSPENDED`) from the central `get_current_user` dependency, so direct API calls cannot bypass it. Email only matches an unbound, unexpired invitation in the same organisation and tenant. The first Super Admin comes from tenant-validated configuration, never from "first to sign in". See [user-access-management.md](user-access-management.md).
- **No user enumeration.** Every refusal returns the same generic message. The reason is recorded only in the audit log (throttled to once per identity and reason every 10 minutes). Failed authentications are rate limited per client IP and access denials per identity (`RATE_LIMIT_AUTH_FAILURES_PER_MINUTE`). Only failures are counted, and a valid token is never checked against the budget, so nobody can lock legitimate users out by flooding from a shared (proxy) IP. Unknown signing-key IDs refresh the tenant's keys at most once a minute.
- Every protected endpoint declares its permission and enforces it in FastAPI (`require(Permission.x)`). The UI's permission checks only hide controls. Denials are audited (`authorization.denied`).
- **Organisation isolation.** Every query filters by the caller's `organization_id`. Resources, projects, connections and alerts in another organisation return 404. Tests cover this.
- **Subscription ownership.** The platform identity can often read many organisations' subscriptions (for example every customer that delegated access through Lighthouse), so being readable is not proof of ownership. When a connection is created or a subscription added, the subscription must not be actively connected to another organisation (also enforced by a unique index), and its home tenant, as reported by Azure, must be the organisation's own Entra tenant or one a platform operator approved for it in `ORGANIZATION_AZURE_TENANTS` (JSON: `{"<org-tenant-id>": ["<azure-tenant-id>"]}`). The subscription picker applies the same rules. With the mock provider (demo data) the tenant rule does not apply.
- Role changes cannot escalate: nobody can assign a role above their own, manage a user ranked above them, change their own role or status, or edit Entra-managed roles. The last active Super Admin cannot be demoted, suspended or deactivated. Users are never deleted, only suspended or deactivated, so their audit history is preserved.
- On sign-out, the SPA clears all cached API data before calling MSAL `logoutRedirect`. When any request reports that access was revoked, it drops cached data and replaces the application with the access page.

### Log query safety

- Queries run **resource-centric** (`LogsQueryClient.query_resource`) against a resource that must be discovered, non-deleted and in the caller's organisation. Azure therefore scopes results to that resource's data.
- Free-form KQL needs `logs:run_kql` and passes `kql_guard.validate_kql`, which rejects:
  - management commands (`.show`, `.drop` and so on)
  - cross-scope functions (`workspace()`, `app()`, `resource()`, `cluster()`, `database()`, `adx()`, `arg()`, `entity_group()`)
  - `externaldata`, `external_table` and `materialized_view`
  - `evaluate` plugins outside an allow-list (for example `http_request` and `sql_request` are blocked)
  - queries over 10,000 characters

  The checks run on the query with `//` comments removed (string literals are respected), so a comment cannot split a forbidden name from its arguments.
- Search and severity filters are appended as escaped KQL string literals, never concatenated raw.
- Results are capped at `LOG_QUERY_MAX_ROWS` (default 5,000), with a 60-second server timeout. Custom queries are audited (`logs.kql_executed`, query truncated to 500 characters) and rate limited (`RATE_LIMIT_KQL_PER_MINUTE`, default 30).

### Input, output and transport

- Pydantic validates every request body and query parameter: GUIDs, slugs, enumerations, lengths, list sizes and time ranges. Validation errors return field locations only and never echo submitted values.
- Structured errors (`{"error": {"code", "message", "request_id"}}`). Unhandled exceptions return `INTERNAL_ERROR` without internals. Azure error messages are shortened and redacted before display.
- Rate limiting: `RATE_LIMIT_PER_MINUTE` (default 300) per user, counted in Redis (or in process memory without Redis). Front Door WAF adds managed rule sets, bot protection and an IP rate limit in Azure.
- API security headers: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP, `Permissions-Policy`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Cache-Control: no-store`, and HSTS outside development and test.
- The nginx web container sends a strict CSP (`script-src 'self'`, `connect-src 'self' https://login.microsoftonline.com`, `frame-ancestors 'none'`, `object-src 'none'`), plus nosniff, frame denial, referrer policy and HSTS. The SPA build uses no inline scripts and no `eval`.
- CORS is limited to `CORS_ORIGINS`, with no credentials (bearer tokens only) and a fixed list of methods and headers. Wildcard origins are refused outside development.
- In production, TLS terminates at Front Door (TLS 1.2 minimum, HTTPS redirect). Origins are private (Private Link to an internal Container Apps environment), and PostgreSQL, Redis and Key Vault are on private networking.

### Safe defaults

- `ENVIRONMENT` defaults to `production`, so a deployment that omits it gets production rules. `AUTH_MODE=dev`, `AZURE_PROVIDER=mock` and `TASK_BACKEND=inline` are refused at start-up unless `ENVIRONMENT` is `development` or `test`. `AUTH_MODE=entra` requires the Entra settings. Outside development, `TASK_BACKEND=celery` requires `REDIS_URL`, and the default development database credentials are refused.
- OpenAPI documentation is disabled in production.
- Discovery stores only an allow-list of resource properties, never full ARM `properties`. Tags prefixed `hidden-` are dropped.
- Logs redact bearer tokens, JWTs and secret-bearing query parameters. Azure SDK HTTP logging is suppressed. Audit `details` drop keys resembling tokens, secrets, passwords, keys, cookies or URLs, and redact string values.
- `X-Forwarded-For` is trusted only for `TRUSTED_PROXY_COUNT` hops (default 0).

### Supply chain

At the time of writing (30/09/2026), `pip-audit -r requirements.txt` found no known vulnerabilities after upgrading PyJWT and FastAPI/Starlette. `npm audit` found 0 vulnerabilities after moving Vitest to 5.x. `bandit -r app -ll` reported no issues. CI repeats these checks, together with CodeQL, Gitleaks and Trivy image scanning, and Dependabot is configured. The CI workflows have not yet been run.

## Audit log

Recorded actions include:

- `user.login_allowed`, `user.login_denied`, `user.access_denied`, `authorization.denied`
- `user.invited`, `user.activated`, `user.bootstrapped`, `user.suspended`, `user.reactivated`, `user.deactivated`, `user.role_changed`, `user.updated`
- `project.created/updated/deleted`, `environment.*`
- `azure.connection.created/updated/disconnected`, `azure.sync.started`
- `resource.assignment_changed`, `dashboard.changed/reset`
- `alert_rule.created/changed/deleted`, `alert.acknowledged/resolved`
- `notification_channel.*`, `health_threshold.changed`
- `logs.kql_executed`, `logs.kql_denied`

Each entry stores the user, actor, action, target, result (`success`, `failure`, `denied`), IP (proxy-aware), user agent, request ID and sanitised details.

## Known gaps and recommendations

- **Not yet tested against live Azure or deployed.** Validate token configuration, RBAC and network rules in a staging subscription first.
- Without Redis, rate-limit counters and the cache are **per process**. Always run with Redis in shared environments.
- `/metrics` is unauthenticated. Restrict it at the ingress, and do not route it through Front Door.
- Azure Cache for Redis still uses an access key (held in Key Vault). Move to Entra authentication when it is added to the backend.
- The PostgreSQL managed identity is configured as an Entra administrator. Replace this with a least-privilege database role after bootstrap.
- Authorisation is organisation-wide. **Project-level access control is Phase 2.**
- Log queries are authorised per resource. There is no per-table restriction within a resource's data.
- Email notifications are not implemented, so invitations are not emailed. The administrator tells the user to sign in.
- Users are added by email or UPN rather than picked from the directory, because the platform deliberately has no Microsoft Graph permissions. A typo creates an invitation that no one can redeem (it expires after 30 days).
