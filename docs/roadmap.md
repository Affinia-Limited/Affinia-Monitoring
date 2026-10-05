# Roadmap and status

Status as at 30/09/2026. "Implemented" means the feature is in code and covered by automated tests. It does not mean it has been verified against a live Azure subscription; none of the Azure integrations have been yet.

## Phase 1: core platform

| Item | Status |
| --- | --- |
| Entra ID authentication (MSAL SPA, validated tokens in the API) | Implemented |
| Application RBAC (four roles, server-side enforcement, audit of denials) | Implemented |
| Admin-controlled access (invitations bound to Entra object ID on first sign-in, suspend, reactivate, deactivate, configuration-only first Super Admin) | Implemented 05/10/2026; tested with mocked RS256/JWKS tokens, not yet against a real tenant |
| Projects and environments | Implemented |
| Azure connections with no stored credentials | Implemented |
| Subscription verification and Resource Graph discovery | Implemented; tested with mocked SDK clients |
| Scheduled synchronisation (upsert by ARM ID, removal tracking, tag mapping) | Implemented |
| App Service, Azure SQL and Front Door monitoring | Implemented |
| Automatic dashboard generation from templates | Implemented |
| Log Analytics queries (predefined and guarded custom KQL) | Implemented |
| Basic alerts (metric rules, acknowledge, resolve, auto-resolve) | Implemented |
| Health model with configurable thresholds | Implemented |
| Global search and filters | Implemented; search understands project + environment terms and returns context |
| Project-first dashboard (overview, project, environment and resource pages with breadcrumbs, health summaries, key metrics) | Implemented 06/10/2026; tested with mock data, not against live Azure |
| Audit logging | Implemented |
| Platform health endpoints, Prometheus metrics, JSON logs | Implemented |
| Docker, Compose, CI/CD (OIDC), Bicep | Written; Bicep compiles; not executed or deployed |

## Phase 2

| Item | Status |
| --- | --- |
| Application Insights (requests, failures, dependencies, availability, traces, application map) | Implemented as a monitor plugin and through App Service related queries |
| More resource types | 22 monitors implemented (see [dashboard-templates.md](dashboard-templates.md)) |
| Microsoft Teams and Slack notifications | Implemented (Key Vault secret references) |
| Email notifications | Placeholder; not implemented |
| Environment comparison | Implemented |
| Dashboard customisation | Implemented: in-app Customise mode, `PATCH`, reset to template |
| Advanced alerts (multi-condition rules, dynamic thresholds, log-based alerts, importing Azure Monitor alerts, maintenance windows) | Not started |
| Advanced RBAC (project- and environment-scoped access, group-based mapping) | Not started |
| Grafana integration (Grafana can already scrape `/metrics`; no Grafana dashboards are provisioned) | Not started |
| Redis Entra authentication | Not started |

## Phase 3

| Item | Status |
| --- | --- |
| Multi-tenant support | Data model is organisation-scoped and allowed tenants get separate organisations. No tenant administration UI or per-organisation settings UI |
| Advanced analytics, cost monitoring, capacity planning | Not started |
| AI-assisted incident analysis | Not started |

## Recommended next steps

1. Connect a non-production subscription with a real managed identity and verify each sync step, the App Service, SQL and Front Door dashboards, and the log queries.
2. Run the CI workflow and a staging deployment (`what-if`, then deploy).
3. Extend the dashboard editor (additional widget types, custom dashboards not tied to a resource).
4. Add project-scoped RBAC.
