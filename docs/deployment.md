# Deployment

The Bicep templates and their deployment steps are documented in [infra/README.md](../infra/README.md). This page summarises the architecture and pipeline.

## Production architecture

```text
Internet
   |  HTTPS only, TLS 1.2+
Azure Front Door Premium + WAF (Microsoft default rule set, bot manager, rate limiting)
   |  Private Link
Container Apps environment (internal, VNet-integrated)
   |-- web      nginx: React build + /api reverse proxy
   |-- api      FastAPI (internal ingress)
   |-- worker   Celery worker: discovery, sync, health, alerts
   |-- beat     Celery beat (one replica)
   '-- migrate  Container Apps job: alembic upgrade head
        |-- PostgreSQL 16 Flexible Server   delegated subnet, private access, Entra auth only
        |-- Azure Cache for Redis           private endpoint, TLS only
        |-- Key Vault                       private endpoint, RBAC, purge protection
        '-- Azure APIs                      Resource Graph, Monitor Metrics, Log Analytics (read-only RBAC)
Container Registry (admin user disabled, AcrPull)
Log Analytics (container logs) and an Application Insights resource (not yet wired: the app sends no telemetry to it)
One user-assigned managed identity for all containers
```

| Concern | Implementation |
| --- | --- |
| Identity | User-assigned managed identity: `AZURE_CLIENT_ID` is set on every container |
| Database auth | `DATABASE_AUTH=entra`, with a password-less `DATABASE_URL` (`?ssl=require`). The backend obtains a token for `https://ossrdbms-aad.database.windows.net/.default` for each new connection |
| Secrets | Only the Redis URL, as a Key Vault reference. No passwords, client secrets or connection strings in templates |
| Networking | Front Door is the only public entry to the app. The API, database, Redis and Key Vault are private. The Container Registry (Standard SKU) keeps public network access, protected by Entra authentication with the admin user disabled |
| Monitored subscriptions | Grant the managed identity Reader, Monitoring Reader and Log Analytics Reader ([azure-rbac.md](azure-rbac.md)) |

## CI/CD

### CI (`.github/workflows/ci.yml`)

| Job | Steps |
| --- | --- |
| Backend | Ruff lint and format check, mypy, pytest with coverage, then Alembic upgrade, drift check and downgrade against a PostgreSQL service |
| Frontend | `npm ci`, lint, type check, tests, build |
| Security | pip-audit, Bandit, `npm audit --audit-level=high`, Gitleaks |
| Docker | Build the backend, worker and frontend images (no push on pull requests), Trivy scan |

CodeQL runs in `.github/workflows/codeql.yml`. Dependabot covers pip, npm, GitHub Actions and Docker.

### Deploy (`.github/workflows/deploy.yml`)

Triggered manually or by pushing a `v*` tag, in the protected `production` GitHub environment. The first job runs the whole CI workflow on the same commit; nothing is deployed unless it passes.

1. `azure/login` with **OIDC federation**. There is no `AZURE_CLIENT_SECRET` anywhere. Identifiers come from GitHub environment variables.
2. Ensure the resource group exists, then deploy the foundation (phase 1: network, identity, Key Vault, ACR, PostgreSQL, Redis, monitoring).
3. `az acr login`, then build and push the backend, worker and frontend images tagged with the commit SHA. The frontend receives the `VITE_ENTRA_*` values as build arguments.
4. On existing deployments, run the migration job with the new image before the apps are updated. The previous revision keeps serving while it runs, so every migration must be backward compatible with the running code (expand first, remove columns in a later release).
5. Deploy the applications (phase 2: Container Apps, migrate job, Front Door).
6. Make sure migrations are at head.

On the first deployment, approve the Front Door Private Link connection once, as described in `infra/README.md`.

### Migrations

Schema changes are made only through Alembic migrations, run by the `migrate` Container Apps job (`scripts/run-migration-job.sh`). The API container does not run migrations in Azure.

## Validation status

The Bicep templates compile and lint without warnings (Bicep CLI 0.47). The templates have **not** been deployed, and the workflows and Docker builds have **not** been executed from this repository yet. Run `az deployment group what-if` and a staging deployment before production.
