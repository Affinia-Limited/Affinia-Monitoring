import { get } from "./client";

/** One deployable ARM template: the alerts whose targets live in one Azure subscription. */
export interface AzureAlertTemplate {
  subscription_id: string;
  subscription_name: string;
  /** Without extension; save as ``<filename>.json``. */
  filename: string;
  alert_count: number;
  template: Record<string, unknown>;
}

export interface AzureAlertExport {
  templates: AzureAlertTemplate[];
  /** Rules that could not be expressed as Azure metric alerts, with the reason. */
  skipped: { resource_name: string; rule: string; reason: string }[];
  /** Resources that received at least one alert. */
  resources: number;
}

export interface AzureAlertExportParams {
  project_id?: string | null;
  environment_id?: string | null;
  resource_id?: string | null;
  include_health?: boolean;
  include_rules?: boolean;
  /** Comma-separated email addresses for the template's action group. */
  recipients?: string;
  action_group_name?: string;
}

export const exportAzureAlerts = (params: AzureAlertExportParams) =>
  get<AzureAlertExport>("/alert-rules/azure-export", params as Record<string, unknown>);

const EMAIL = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/;

/** Splits a comma, semicolon or newline separated list; returns the valid (lower-cased, unique) and invalid entries. */
export function parseRecipients(raw: string): { valid: string[]; invalid: string[] } {
  const items = raw
    .split(/[,;\s]+/)
    .map((v) => v.trim().toLowerCase())
    .filter(Boolean);
  const unique = [...new Set(items)];
  return { valid: unique.filter((v) => EMAIL.test(v)), invalid: unique.filter((v) => !EMAIL.test(v)) };
}

export function deployCommand(t: Pick<AzureAlertTemplate, "subscription_id" | "filename">): string {
  return `az deployment group create --resource-group <your-resource-group> --subscription ${t.subscription_id} --template-file ${t.filename}.json`;
}
