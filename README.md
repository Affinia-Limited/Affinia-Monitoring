# Azure Monitoring Platform

An internal web application that connects to one or more Azure subscriptions, discovers their resources automatically through Azure Resource Graph, and generates monitoring dashboards for each resource from type-specific templates. It covers multiple projects and environments, calculates resource health from real monitoring signals, evaluates alert rules, and provides scoped Log Analytics and Application Insights queries.

The platform never stores Azure credentials. It authenticates as its own Managed Identity or Workload Identity, which you grant read-only Azure RBAC roles.

## Features

| Area | Summary |
| --- | --- |
| Authentication | Microsoft Entra ID (MSAL in the SPA, full token validation in FastAPI) |
| Authorisation | Super Admin, Admin, Operator and Viewer roles, enforced server-side on every endpoint |
| Projects | Projects with environments (Development, UAT, Staging, Production, Other); resources mapped by Azure tags or connection defaults |
| Azure connections | Add a tenant and subscriptions with no secrets. Discovery runs in the background with step-by-step progress |
| Discovery and sync | Resource Graph discovery; upsert by ARM resource ID; removed resources are marked deleted; scheduled re-sync (default every 15 minutes) |
| Dashboards | Generated automatically per resource type (22 monitor plugins, including App Service, Function App, App Service Plan, Azure SQL, Front Door Standard/Premium and classic, Application Insights, Storage, Key Vault, ACR, Cosmos DB, Redis, VMs, AKS, Service Bus, Event Hubs, Application Gateway, Load Balancer and Public IP) |
| Metrics | A single `MetricService` abstraction over Azure Monitor Metrics, with caching, dimension splits and related-resource metrics |
| Logs | Predefined and custom KQL, executed resource-centric, with a KQL guard, row cap, rate limit and audit trail |
| Health | Healthy, Warning, Critical or Unknown, derived from Azure Resource Health, ARM state and metric rules with configurable thresholds |
| Alerts | Metric alert rules, de-duplicated alerts, acknowledge and resolve, notification channels (webhook, Microsoft Teams and Slack; email is a placeholder) |
| Comparison | Key metrics compared side by side across a project's environments |
| Search and filters | Global search across projects, environments, resources and subscriptions; filters by project, environment, subscription, resource group, type, region, health and time range |
| Audit | Administrative actions, sign-ins and authorisation denials, never including tokens or secrets |
| Platform observability | `/live`, `/ready`, `/health`, Prometheus `/metrics` and structured JSON logs with request IDs |

## Architecture

```text
Browser (React + MSAL) --HTTPS--> nginx (static SPA, /api proxy) --> FastAPI API
                                                                      |   |   |
                                                PostgreSQL <----------+   |   +--> Azure Resource Graph, Monitor
                                                Redis (cache, broker) <---+        Metrics, Log Analytics,
                                                Celery worker + beat (sync, health, alerts)   App Insights
```

See [docs/architecture.md](docs/architecture.md) for the full description.

## Quick start

### Docker Compose (recommended)

```bash
docker compose up --build
```

- Web UI: http://localhost:8080
- API documentation: http://localhost:8000/api/docs

By default the stack runs with `AUTH_MODE=dev` (no sign-in, clearly bannered) and `AZURE_PROVIDER=mock` (a deterministic demo estate, labelled "Demo data" throughout the UI). You do not need an Azure subscription or an Entra app registration to try it. To connect the demo estate, open Azure Connections, choose Add Azure subscription and accept the pre-filled mock tenant and subscriptions.

### Without Docker

You need Python 3.12, Node.js 22 or later, and PostgreSQL 16.

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt        # on Linux or macOS: .venv/bin/pip
export ENVIRONMENT=development AUTH_MODE=dev AZURE_PROVIDER=mock TASK_BACKEND=inline
export DATABASE_URL=postgresql+asyncpg://<user>:<password>@localhost:5432/monitoring
alembic upgrade head
uvicorn app.main:app --port 8000

# Frontend (second terminal)
cd frontend
npm ci
npm run dev        # http://localhost:5173, which proxies /api to http://localhost:8000
```

`TASK_BACKEND=inline` runs background jobs inside the API process so Redis is not required. It is refused outside development and test. See [docs/local-development.md](docs/local-development.md).

### Connecting a real subscription

Set `AZURE_PROVIDER=azure`, give the platform identity read-only roles, and configure Entra ID. Follow [docs/azure-setup.md](docs/azure-setup.md), [docs/azure-rbac.md](docs/azure-rbac.md) and [docs/entra-id.md](docs/entra-id.md).

## Repository layout

```text
backend/            FastAPI application, Alembic migrations, tests
  app/api/          Routers (v1) and platform health endpoints
  app/core/         Configuration, security, permissions, errors, logging, cache, metrics
  app/models/       SQLAlchemy 2.x models
  app/schemas/      Pydantic request and response models
  app/services/     Azure services (real and mock), monitors (plugins), discovery, health,
                    alerts, dashboards, KQL guard, audit
  app/workers/      Celery application and tasks
frontend/           React, TypeScript, Vite, Tailwind CSS, Recharts, TanStack Query, MSAL
infra/              Bicep for the Azure production architecture (see infra/README.md)
.github/workflows/  CI, CodeQL and OIDC deployment pipelines
scripts/            Development and migration helper scripts
docs/               Documentation
```

## Testing

```bash
# Backend
cd backend
ruff check app tests && ruff format --check app tests
mypy app
pytest                                    # 131 tests, SQLite by default
TEST_DATABASE_URL=postgresql+asyncpg://... pytest   # the same suite against PostgreSQL

# Frontend
cd frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

The unit tests do not need an Azure subscription. The real Azure service classes are tested with the Azure SDK clients mocked, and the API is tested against the mock provider. Authentication tests use real RS256-signed tokens validated against a mocked JWKS endpoint.

## Security principles

- No Azure passwords or client secrets are stored anywhere. The platform uses its own Managed Identity or Workload Identity (`DefaultAzureCredential`, with environment and interactive credentials excluded).
- Genuine secrets, such as notification webhook URLs, live in Azure Key Vault. The database stores only the secret name.
- Every protected endpoint validates the Entra token (signature, issuer, audience, lifetime, tenant, scope or role) and enforces permissions in FastAPI.
- Organisation isolation on every query, resource-centric log queries, a KQL guard, rate limiting and audit logging.
- Development-only modes are refused by configuration validation outside development and test.

Details are in [docs/security.md](docs/security.md).

## Documentation

| Document | Content |
| --- | --- |
| [architecture.md](docs/architecture.md) | Components, data model, request and job flows |
| [local-development.md](docs/local-development.md) | Running and testing locally |
| [azure-setup.md](docs/azure-setup.md) | Connecting real Azure subscriptions |
| [entra-id.md](docs/entra-id.md) | App registrations and token validation |
| [user-access-management.md](docs/user-access-management.md) | Admin-controlled access: first Super Admin, adding, suspending and removing users |
| [azure-rbac.md](docs/azure-rbac.md) | Minimum Azure roles per capability and scope |
| [monitoring.md](docs/monitoring.md) | Health, alerts, notifications, sync, caching, platform observability |
| [dashboard-templates.md](docs/dashboard-templates.md) | Template engine and widget reference |
| [adding-resource-types.md](docs/adding-resource-types.md) | Writing a monitor plugin (worked example) |
| [api.md](docs/api.md) | REST API reference with required permissions |
| [security.md](docs/security.md) | Threat model, controls and known gaps |
| [deployment.md](docs/deployment.md) | Azure production architecture and CI/CD |
| [troubleshooting.md](docs/troubleshooting.md) | Error codes, symptoms and fixes |
| [roadmap.md](docs/roadmap.md) | Phase status |

## Status and limitations

As at 30/09/2026:

- The backend (lint, type check, 131 tests on SQLite and PostgreSQL) and the frontend (lint, type check, tests, production build) pass locally. `pip-audit`, `npm audit` and `bandit` report no findings.
- The full stack was run end to end locally against PostgreSQL with the mock Azure provider, and the UI was rendered in a headless browser.
- **The real Azure integration has not yet been run against a live subscription.** It is implemented against the Azure SDKs (Resource Graph, Monitor Metrics, Logs, ARM subscriptions, Key Vault) and tested with mocked SDK clients.
- Docker images and the GitHub Actions workflows were written but not executed on the development machine, because Docker was not available. The Bicep templates compile and lint cleanly but have not been deployed.
- Email notifications are a placeholder. Webhook, Teams and Slack senders are implemented.
- Dashboards can be customised in the UI (Customise mode: add, remove, resize and reorder widgets) by users with `dashboards:manage`, and reset to their template. Customised dashboards are never overwritten by template upgrades.
- Project-level access control, Grafana integration and cost monitoring are later phases. See [docs/roadmap.md](docs/roadmap.md).
