# Azure RBAC

Monitoring is read-only. The platform identity never needs **Owner**, **Contributor** or any role with write, delete or `Microsoft.Authorization/*/write` actions. The platform issues only `read` operations: Resource Graph queries, ARM subscription reads, metric reads, and log query reads. It does not create diagnostic settings, alert rules or any other Azure resource. Granting more than the roles below only increases the impact if the identity were ever compromised.

## Monitored subscriptions

| Capability | API used by the platform | Built-in role | Scope |
| --- | --- | --- | --- |
| Subscription verification | ARM `subscriptions/get`, `subscriptions/list` | Reader | Subscription |
| Resource discovery | Resource Graph `resources` and `resourcecontainers` tables | Reader | Subscription (recommended) or resource group |
| Resource Health | Resource Graph `healthresources` table | Reader or Monitoring Reader | Subscription or resource group |
| Service Health | Resource Graph `servicehealthresources` table | Reader or Monitoring Reader | Subscription |
| Recent changes | Resource Graph `resourcechanges` table | Reader | Subscription or resource group |
| Metrics | Azure Monitor Metrics (`Microsoft.Insights/metrics/read`) | Monitoring Reader | Subscription or resource group |
| Log queries (resource-centric) | Log Analytics query API against the resource ID | Log Analytics Reader, plus read on the resource | Workspace(s) receiving diagnostics, and the resources |
| Workspace queries | Log Analytics query API against the workspace resource ID | Log Analytics Reader | Workspace |
| Application Insights telemetry | Resource-centric query against the component | Monitoring Reader or Reader (both include `Microsoft.Insights/components/*/read`); Log Analytics Reader for workspace-based components | Component, and its workspace |

Notes:

- **Resource-group scope.** Granting Reader only on resource groups works, but discovery then returns only resources in those groups. The "verify subscriptions" step reads the subscription itself, which needs read at subscription scope. Without it, the sync fails at that step with `AZURE_PERMISSION_DENIED`. Subscription-scope Reader is the practical minimum.
- **Resource-context log access.** Resource-centric queries depend on the workspace access control mode. With "Use resource or workspace permissions" (resource-context), read on the resource is sufficient to query its own logs. With "Require workspace permissions", the identity also needs Log Analytics Reader on the workspace. Granting Log Analytics Reader on the relevant workspaces works in both modes.
- Reader alone already includes `Microsoft.Insights/metrics/read` and Log Analytics read actions at resource level. Monitoring Reader is still recommended explicitly, because it covers Monitor data at any scope and makes the intent auditable.

### Example assignments

```bash
PRINCIPAL_ID=<managed-identity-principal-object-id>
SUB=/subscriptions/<subscription-id>

az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Reader" --scope "$SUB"
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Monitoring Reader" --scope "$SUB"
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Log Analytics Reader" \
  --scope "$SUB/resourceGroups/<rg>/providers/Microsoft.OperationalInsights/workspaces/<workspace>"
```

`GET /api/v1/azure/identity` (permission `azure:connect`) returns the identity's client ID, home tenant and this role list, so administrators can see what to grant from the UI.

## The platform's own resources

| Resource | Role | Why |
| --- | --- | --- |
| Platform Key Vault | Key Vault Secrets User | Read notification endpoint secrets (`secret_ref`) and the Redis URL reference |
| Azure Container Registry | AcrPull | Pull images |
| PostgreSQL Flexible Server | Microsoft Entra administrator or a database role mapped to the managed identity | Token-based login with `DATABASE_AUTH=entra` (the access token for `https://ossrdbms-aad.database.windows.net/.default` is the password) |

The Bicep in `infra/` creates the Key Vault and ACR assignments and sets the identity as a PostgreSQL Entra administrator. After the first deployment, consider replacing the administrator mapping with a least-privilege database role that owns only the application schema.

The GitHub deployment identity (OIDC federated credential) needs rights to deploy to the platform's resource group, typically Contributor on that resource group only, plus the rights to create the role assignments above (for example Role Based Access Control Administrator, constrained to those roles). It needs nothing on monitored subscriptions.

## Other tenants

**Recommended: Azure Lighthouse.** The customer tenant delegates Reader, Monitoring Reader and Log Analytics Reader on its subscriptions to the platform's managed identity (or a group containing it). The identity then reads delegated subscriptions with its home-tenant token. There are no guest accounts or secrets, and the customer can revoke access at any time. See `infra/README.md` for an outline.

**Alternative: a multi-tenant app registration with workload identity federation.** Consent the app in the customer tenant, grant the same roles to its service principal there, and list the customer tenant in `AZURE_ADDITIONALLY_ALLOWED_TENANTS`. For each connection whose `tenant_id` differs from `AZURE_TENANT_ID`, the platform wraps its credential in `TenantScopedCredential`, which requests tokens for that tenant. Managed identities are single-tenant, so this path needs workload identity (or another federated credential) rather than a plain managed identity.
