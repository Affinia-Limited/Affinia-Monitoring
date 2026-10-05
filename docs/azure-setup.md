# Connecting Azure

## How access works

The platform never asks for, stores or transmits Azure credentials. It authenticates as **its own identity** through `DefaultAzureCredential`:

| Where the platform runs | Identity used |
| --- | --- |
| Azure Container Apps / App Service | User-assigned Managed Identity (`AZURE_CLIENT_ID` = its client ID) |
| AKS or another federated environment | Workload Identity (`AZURE_CLIENT_ID` = the federated app's client ID) |
| A developer workstation (`ENVIRONMENT=development` only) | Azure CLI, Azure Developer CLI or Azure PowerShell sign-in |

Environment-variable service principal secrets (`EnvironmentCredential`), interactive browser sign-in, the shared token cache and VS Code credentials are explicitly excluded. Developer credentials are excluded outside `development`.

You grant this identity read-only roles on the subscriptions you want monitored. An "Azure connection" in the platform records only the tenant ID, the subscription IDs and sync settings.

## Steps

1. **Deploy or run the platform** with `AZURE_PROVIDER=azure`. Set `AZURE_TENANT_ID` (the identity's home tenant) and `AZURE_CLIENT_ID` (the managed or workload identity client ID).
2. **Grant roles** to the identity on each subscription, as described in [azure-rbac.md](azure-rbac.md):
   - Reader
   - Monitoring Reader
   - Log Analytics Reader on the workspaces that hold diagnostic logs
3. **Send diagnostics to Log Analytics.** Logs and query-performance views need diagnostic settings on each resource:
   - App Service: `AppServiceHTTPLogs`, `AppServiceConsoleLogs`, `AppServiceAppLogs`, `AppServicePlatformLogs`
   - Azure SQL: `QueryStoreRuntimeStatistics`, `Errors`, `Deadlocks`, `Timeouts`, `Blocks`
   - Front Door Standard/Premium: `FrontDoorAccessLog`, `FrontDoorHealthProbeLog`, `FrontDoorWebApplicationFirewallLog`

   Metrics do not need diagnostic settings.
4. **Create projects and environments** (Projects, then New project). Set tag values so resources map automatically. For example, project `crm` matches resources tagged `project=CRM`, and environment kind `production` matches `environment=prod`, `production`, `prd` or `live`.
5. **Add the connection.** Go to Azure Connections, choose Add Azure subscription, and enter the tenant ID and subscription IDs. "Load subscriptions the platform can already read" calls `GET /api/v1/azure/available-subscriptions`, which lists the subscriptions the identity can see. Optionally choose a default project and environment for resources whose tags do not match.
6. **Watch the progress.** The wizard shows each sync step: authenticate, verify subscriptions, verify read permissions, discover, categorise and assign, apply dashboard templates, evaluate health.

Add further subscriptions later by editing the connection (`add_subscription_ids`) or adding another connection. No code changes are needed. A subscription can belong to only one connection per organisation (error `SUBSCRIPTION_ALREADY_CONNECTED`). A disconnected subscription can be reconnected, and its history is kept.

## Other tenants

Use **Azure Lighthouse** so the customer delegates Reader, Monitoring Reader and Log Analytics Reader to your identity. The platform then uses its home-tenant token directly. The alternative is a multi-tenant app registration with workload identity federation, listing the customer tenant in `AZURE_ADDITIONALLY_ALLOWED_TENANTS`. See [azure-rbac.md](azure-rbac.md#other-tenants).

## Resource mapping settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `PROJECT_TAG_KEYS` | `project,Project,application` | Tag keys checked, in order, for the project |
| `ENVIRONMENT_TAG_KEYS` | `environment,Environment,env` | Tag keys checked, in order, for the environment |

Tag key comparison is case-insensitive. Resource-group tags apply when the resource itself lacks the tag. Manual assignments (`PUT /api/v1/resources/{id}/assignment`) are pinned and survive sync.

## What discovery captures

One Resource Graph query per page (1,000 rows, up to 100 pages per subscription batch) returns every resource in the connected subscriptions. Only an allow-list of non-sensitive properties is stored:

`provisioningState`, `state`, `status`, `defaultHostName`, `serverFarmId`, `currentServiceObjectiveName`, `maxSizeBytes`, `fullyQualifiedDomainName`, `workspaceResourceId`, `appInsightsResourceId`, `customerId`, `vmSize`, `kubernetesVersion`, `skuTier`, `skuCapacity`

Tags beginning `hidden-` are dropped. The App Service link to Application Insights is read from the `hidden-link: /app-insights-resource-id` tag into `appInsightsResourceId`.

## Verification status

The real Azure code paths (Resource Graph pagination, ARM subscription reads, Metrics grouping and dimension splits, resource-centric log queries, and error mapping) are covered by tests with the Azure SDK clients mocked. They have **not** yet been exercised against a live subscription. Run a first connection against a non-production subscription and review the sync run and several dashboards before relying on it.
