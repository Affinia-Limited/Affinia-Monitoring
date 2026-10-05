// Test fixtures only. Shapes mirror the API contract; values are arbitrary.
import type { Alert, EnvironmentSummary, HealthCounts, Me, MetricOut, Project, ResourceDetail, Widget } from "@/types/api";

export const ALL_PERMISSIONS = [
  "alerts:acknowledge",
  "alerts:manage",
  "alerts:view",
  "audit:view",
  "azure:connect",
  "azure:sync",
  "dashboards:manage",
  "dashboards:view",
  "logs:run_kql",
  "logs:view",
  "projects:manage",
  "resources:view",
  "settings:manage",
  "users:manage",
];

export function me(overrides: Partial<Me> = {}): Me {
  return {
    id: "u1",
    organization_id: "o1",
    organization_name: "Test organisation",
    email: "admin@example.test",
    display_name: "Test Admin",
    role: "super_admin",
    permissions: ALL_PERMISSIONS,
    role_managed_by_entra: false,
    auth_mode: "dev",
    azure_provider: "mock",
    ...overrides,
  };
}

export const viewer = me({ role: "viewer", permissions: ["dashboards:view", "resources:view", "alerts:view"] });

export function metric(overrides: Partial<MetricOut> = {}): MetricOut {
  return {
    key: "plan_cpu",
    label: "Plan CPU",
    unit: "percent",
    aggregation: "Average",
    interval_seconds: 300,
    series: [
      {
        name: "Plan CPU",
        dimensions: {},
        points: [
          { timestamp: "2026-09-30T10:00:00+00:00", value: 30 },
          { timestamp: "2026-09-30T10:05:00+00:00", value: 40 },
        ],
      },
    ],
    summary: { avg: 35, min: 30, max: 40, sum: 70, latest: 40 },
    source_resource_id: "plan-1",
    unavailable_reason: null,
    unavailable_message: null,
    is_mock: false,
    ...overrides,
  };
}

export const resource: ResourceDetail = {
  id: "r1",
  azure_id: "/subscriptions/s/resourcegroups/rg/providers/microsoft.web/sites/app-crm-prod-uks",
  name: "app-crm-prod-uks",
  resource_type: "microsoft.web/sites",
  type_display_name: "App Service",
  category: "Compute",
  kind: "app,linux",
  sku: null,
  location: "uksouth",
  subscription_id: "s",
  subscription_name: "Test subscription",
  resource_group: "rg-crm-prod-uks",
  tags: { project: "CRM" },
  monitor_key: "app_service",
  project_id: "p1",
  project_name: "CRM",
  environment_id: "e1",
  environment_name: "Production",
  assignment_source: "tag",
  health_status: "healthy",
  health_reasons: [],
  health_evaluated_at: "2026-09-30T10:00:00+00:00",
  health_metrics: [],
  active_alerts: 0,
  azure_availability_state: "Available",
  last_seen_at: "2026-09-30T10:00:00+00:00",
  first_seen_at: "2026-09-29T10:00:00+00:00",
  dashboard_id: "d1",
  properties: { skuCapacity: 3 },
  related: { app_service_plan: "plan-1", app_insights: null },
  summary_metrics: ["plan_cpu"],
  portal_url: "https://portal.azure.com/",
};

export function counts(c: Partial<HealthCounts> = {}): HealthCounts {
  const base = { healthy: 0, warning: 0, critical: 0, unknown: 0, ...c };
  return { ...base, total: c.total ?? base.healthy + base.warning + base.critical + base.unknown };
}

export function environment(overrides: Partial<EnvironmentSummary> = {}): EnvironmentSummary {
  return {
    id: "e1",
    project_id: "p1",
    name: "Production",
    slug: "prod",
    kind: "production",
    sort_order: 0,
    tag_values: [],
    status: "healthy",
    health: counts(),
    active_alerts: 0,
    last_checked_at: null,
    ...overrides,
  };
}

/** Values are arbitrary: the UI must work for any project and any set of environments. */
export function project(overrides: Partial<Project> = {}): Project {
  return {
    id: "p1",
    name: "Project One",
    slug: "project-one",
    description: "",
    tag_values: [],
    created_at: "2026-09-30T10:00:00Z",
    status: "healthy",
    active_alerts: 0,
    last_checked_at: null,
    health: counts(),
    environments: [environment()],
    ...overrides,
  };
}

export function widget(overrides: Partial<Widget>): Widget {
  return { id: "w", position: 0, section: "Overview", widget_type: "metric_card", title: "Widget", width: 3, config: {}, ...overrides };
}

export function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: "a1",
    rule_id: "rule1",
    resource_id: "r1",
    resource_name: "app-crm-prod-uks",
    resource_type: "microsoft.web/sites",
    type_display_name: "App Service",
    project_id: "p1",
    project_name: "CRM",
    environment_id: "e1",
    environment_name: "Production",
    source: "platform",
    severity: "critical",
    status: "active",
    title: "Plan CPU > 90 on app-crm-prod-uks",
    metric_name: "Plan CPU",
    current_value: 94,
    threshold: 90,
    operator: "gt",
    started_at: new Date(Date.now() - 10 * 60_000).toISOString(),
    last_evaluated_at: null,
    acknowledged_at: null,
    resolved_at: null,
    ...overrides,
  };
}
