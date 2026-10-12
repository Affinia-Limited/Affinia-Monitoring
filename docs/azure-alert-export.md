# Exporting alert rules to Azure Monitor

The platform can export its alerting rules as **Azure Monitor metric alerts** in ARM templates. Deployed to Azure, they are evaluated by Azure Monitor itself and email an action group, independently of this platform (they keep working if the platform is down).

Open **Alerts > Export to Azure** (users with `alerts:manage`), choose a scope, the sources and the email recipients, then **Generate templates**. The API behind it is `GET /api/v1/alert-rules/azure-export` ([api.md](api.md)).

## What is exported

| Source | Alerts |
| --- | --- |
| Health thresholds | For every monitored resource in scope, each health rule of its monitor plugin with your organisation's overrides (Settings > Health rules): a **warning** alert (Azure severity 2) and a **critical** alert (severity 0) where that threshold is set. Disabled rules are skipped |
| Custom alert rules | Every enabled rule (Alerts > Rules) for the resources in its scope (monitor, and optionally resource, project and environment). Severity critical = 0, warning = 2, info = 3 |

Each template also contains one **action group** with an email receiver per recipient. Every alert notifies it when it fires and when it resolves (`autoMitigate`). The template parameters let you change the action group name, its 12-character short name (shown in emails), the recipients and whether the alerts are deployed enabled.

## How a rule becomes an Azure metric alert

| Platform | Azure Monitor |
| --- | --- |
| Metric key (e.g. `response_time`) | `metricName` from the monitor plugin (e.g. `HttpResponseTime`) and its `metricNamespace` (default: the target's resource type) |
| Threshold in display units | Divided by the metric's scale, so it is in Azure's unit (e.g. 1,000 ms becomes 1 for `HttpResponseTime`, which Azure reports in seconds) |
| `gt` / `gte` / `lt` / `lte` | `GreaterThan` / `GreaterThanOrEqual` / `LessThan` / `LessThanOrEqual` |
| Health rule window | `windowSize`: the smallest Azure window (1, 5, 15, 30 minutes, 1, 6, 12 or 24 hours) at least as long as the rule's window and the metric's minimum granularity |
| Evaluation | `evaluationFrequency`: every minute for windows up to 5 minutes, 5 minutes up to 30, 15 minutes up to 6 hours, hourly beyond |
| Health rule reducer | `timeAggregation`: the metric's own aggregation when the reducer combines it naturally (Average with avg, Total with sum, Maximum with max, Minimum with min, Count with sum); otherwise the reducer's equivalent. Custom rules use their own aggregation |
| Metric on a related resource (e.g. App Service plan CPU for an App Service) | The alert targets the related resource (the App Service Plan) and its description names both |

Alert names are deterministic (`amp-<resource>-<metric>-<warning|critical|rule>`), so deploying a newer export again **updates the same alerts in place**. Two resources with the same name in different resource groups get a stable hash suffix.

## Deploying

There is **one template per Azure subscription**: a metric alert can only target resources in the subscription it is deployed to. Deploy each template into any resource group of its subscription (for example a dedicated `rg-monitoring-alerts`).

Azure CLI (the panel copies this command for you):

```bash
az deployment group what-if --resource-group <rg> --subscription <subscription-id> --template-file <file>.json
az deployment group create  --resource-group <rg> --subscription <subscription-id> --template-file <file>.json
```

Override parameters with `--parameters emailReceivers='["ops@contoso.com"]' actionGroupName=prod-oncall`.

Azure portal: **Create a resource > Template deployment (deploy using custom templates) > Build your own template in the editor > Load file**, then choose the subscription and resource group.

The deploying identity needs **Monitoring Contributor** (or Contributor) on the resource group, and read access to the target resources.

## Limitations

- Only metric thresholds are exported. Signals that are not metrics (Azure Resource Health, the app's stopped state, provisioning failures) stay with the platform's own health evaluation. Use Azure Resource Health alerts for those.
- Metrics split by a dimension (for example HTTP status) alert on the total across that dimension.
- A rule whose metric lives on a related resource that has not been discovered is skipped, and the panel lists it with the reason. So is a window longer than 24 hours.
- Overrides and rules changed later are not pushed to Azure automatically: export and deploy again.
- Always check a template with `what-if` before deploying it to production.
- Recipient addresses are not stored by the export and are not written to the audit log. The audit entry (`alerts.azure_exported`) records counts only.
