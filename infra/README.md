# Azure infrastructure (Bicep)

This folder defines the production deployment of the Azure Monitoring Platform. It is deployed at
resource group scope by `main.bicep`.

```text
Internet
   |
Azure Front Door Premium + WAF (HTTPS only, TLS 1.2+, managed rules, rate limiting)
   |  Private Link
Container Apps environment (internal, VNet-integrated, workload profiles)
   |-- web      nginx serving the React build; proxies /api to the api app
   |-- api      FastAPI (internal ingress only)
   |-- worker   Celery worker (discovery, sync, health, alerts)
   |-- beat     Celery beat (exactly one replica)
   '-- migrate  Container Apps job: alembic upgrade head
        |
        |-- PostgreSQL Flexible Server  private access (delegated subnet), Entra auth only
        |-- Azure Cache for Redis       private endpoint, TLS 1.2 only, non-TLS port disabled
        |-- Key Vault                   private endpoint, RBAC, purge protection
        '-- Azure Monitor APIs          Resource Graph, Metrics, Logs (read-only RBAC)

Log Analytics + Application Insights monitor the platform itself.
A single user-assigned managed identity is used by every container.
```

| Module | Resources |
| --- | --- |
| `modules/monitoring.bicep` | Log Analytics workspace, workspace-based Application Insights (local auth disabled) |
| `modules/identity.bicep` | User-assigned managed identity |
| `modules/network.bicep` | VNet with `snet-apps` (/23, Container Apps), `snet-postgres` (/27, delegated), `snet-private-endpoints` (/27) |
| `modules/keyvault.bicep` | Key Vault (RBAC, purge protection, public access disabled) + private endpoint + DNS, *Key Vault Secrets User* for the identity |
| `modules/acr.bicep` | Container Registry (admin user disabled) + *AcrPull* for the identity |
| `modules/postgres.bicep` | PostgreSQL 16 Flexible Server, password auth disabled, Entra admins (DBA group + app identity), TLS required |
| `modules/redis.bicep` | Azure Cache for Redis + private endpoint; the connection URL is written to Key Vault as `redis-url` |
| `modules/containerapps.bicep` | Environment, api / worker / beat / web apps, migrate job |
| `modules/frontdoor.bicep` | Front Door Premium profile, endpoint, Private Link origin, route, WAF policy, optional custom domain |

No template contains a password, client secret or connection string. The only secret is the Redis
access key. The template reads it with `listKeys()` during deployment, writes it straight to Key
Vault, and the containers read it as a Key Vault reference through the managed identity.

## Prerequisites

1. An Entra ID app registration for the API (exposes the `access_as_user` scope and the app roles
   `Monitoring.SuperAdmin`, `Monitoring.Admin`, `Monitoring.Operator`, `Monitoring.Viewer`) and one for
   the SPA. See `docs/entra-id.md`.
2. An Entra group for PostgreSQL administrators.
3. A deployment identity for GitHub Actions using **OIDC federation**. There is no client secret:
   ```bash
   az ad app create --display-name "monitoring-platform-deploy"
   az ad sp create --id <deploy-app-client-id>
   az ad app federated-credential create --id <deploy-app-client-id> --parameters '{
     "name": "github-production",
     "issuer": "https://token.actions.githubusercontent.com",
     "subject": "repo:<org>/<repo>:environment:production",
     "audiences": ["api://AzureADTokenExchange"]
   }'
   # Deploys resources and creates role assignments (ACR pull, Key Vault) in the platform resource group.
   az role assignment create --assignee <deploy-app-client-id> --role Contributor \
     --scope /subscriptions/<platform-subscription-id>/resourceGroups/<resource-group>
   az role assignment create --assignee <deploy-app-client-id> --role "Role Based Access Control Administrator" \
     --scope /subscriptions/<platform-subscription-id>/resourceGroups/<resource-group>
   ```
4. GitHub environment `production` with required reviewers, plus the variables listed at the
   top of `.github/workflows/deploy.yml`.

## Deploying

The deployment has two phases, because the container apps need images that can only be pushed
once the registry exists. The `Deploy` workflow runs both phases automatically. To run it by hand:

```bash
cp infra/main.parameters.example.json infra/main.parameters.json   # fill in; do not commit real values
az deployment group create -g <resource-group> -f infra/main.bicep \
  -p @infra/main.parameters.json deployApps=false

az acr login --name <registry-name>
docker build -t <login-server>/monitoring-backend:<tag> backend
docker build -t <login-server>/monitoring-worker:<tag> -f backend/worker.Dockerfile backend
docker build -t <login-server>/monitoring-frontend:<tag> frontend   # add --build-arg VITE_... values
docker push ... (all three)

az deployment group create -g <resource-group> -f infra/main.bicep \
  -p @infra/main.parameters.json deployApps=true imageTag=<tag>
bash scripts/run-migration-job.sh <resource-group> <namePrefix>-migrate
```

### After the first deployment: approve the Front Door private link

Front Door reaches the internal Container Apps environment over Private Link. The connection has to
be approved once:

```bash
az network private-endpoint-connection list --id <container-apps-environment-resource-id>
az network private-endpoint-connection approve --id <connection-id> --description "Front Door"
```

If you use a custom domain, add the DNS CNAME and the `_dnsauth` TXT record shown on the Front Door
custom domain before the managed certificate is issued.

## Granting read access to monitored subscriptions

The platform identity only needs **read** access. Grant these roles on each subscription (or on
individual resource groups) that you want to monitor. Never grant Owner or Contributor.

| Capability | Role | Scope |
| --- | --- | --- |
| Resource discovery (Resource Graph), metadata, Resource Health | Reader | Subscription or resource group |
| Azure Monitor metrics and alerts | Monitoring Reader | Subscription or resource group |
| Log Analytics and Application Insights queries | Log Analytics Reader | Workspaces / Application Insights components (or their resource group) |

```bash
PRINCIPAL_ID=<identityPrincipalId output of the deployment>
SCOPE=/subscriptions/<monitored-subscription-id>

az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Reader" --scope "$SCOPE"
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Monitoring Reader" --scope "$SCOPE"
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Log Analytics Reader" --scope "$SCOPE/resourceGroups/<rg-containing-workspaces>"
```

### Other tenants: use Azure Lighthouse (recommended)

To monitor subscriptions in another Entra tenant, the recommended approach is **Azure Lighthouse**.
The customer delegates the three read-only roles to the platform's managed identity (or to a group
that contains it). The identity then reads the delegated subscriptions with tokens from its own home
tenant: no guest accounts, no secrets, and the customer can revoke access at any time. The
alternative, a multi-tenant app registration with workload identity federation, is covered in
`docs/azure-rbac.md`.

## Validation status

`main.bicep` and every module compile with `bicep build` and pass `bicep lint` with no errors or
warnings (Bicep CLI v0.47). The templates have **not** been deployed to a subscription from this
repository yet. Run `az deployment group what-if` before the first deployment.

## Known gaps

- **PostgreSQL Entra authentication** is implemented in the backend (`DATABASE_AUTH=entra`: the managed
  identity's token for `https://ossrdbms-aad.database.windows.net/.default` is used as the connection password;
  connections recycle every 30 minutes). The identity must still be created as a PostgreSQL role (see
  `docs/azure-rbac.md`). Not yet exercised against a deployed server.
- **Redis Entra authentication.** Redis currently uses an access key held in Key Vault. Move to Entra
  authentication for Azure Cache for Redis when the backend supports token-based Redis auth.
