// Hand-written mirrors of backend/app/schemas/*. Keep in sync with the FastAPI models.

export type HealthStatus = "healthy" | "warning" | "critical" | "unknown";
export type Severity = "critical" | "warning" | "info";
export type AlertStatus = "active" | "acknowledged" | "resolved";
export type TimeRangePreset = "30m" | "1h" | "6h" | "24h" | "7d" | "30d" | "custom";

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id?: string | null;
  details?: Record<string, unknown> | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Me {
  id: string;
  organization_id: string;
  organization_name: string;
  email: string | null;
  display_name: string | null;
  role: string;
  permissions: string[];
  role_managed_by_entra: boolean;
  auth_mode: "entra" | "dev";
  azure_provider: "azure" | "mock";
}

export interface HealthCounts {
  healthy: number;
  warning: number;
  critical: number;
  unknown: number;
  total: number;
}

export type EnvironmentKind = "development" | "uat" | "staging" | "production" | "other";

export interface EnvironmentOut {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  kind: EnvironmentKind | string;
  sort_order: number;
  tag_values: string[];
}

/** Health covers monitored resources only (inventory items such as NICs carry no health signal). */
export interface EnvironmentSummary extends EnvironmentOut {
  health: HealthCounts;
  status: HealthStatus;
  active_alerts: number;
  /** Most recent health evaluation in this environment. */
  last_checked_at: string | null;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string;
  tag_values: string[];
  created_at: string;
  environments: EnvironmentSummary[];
  health: HealthCounts;
  status: HealthStatus;
  active_alerts: number;
  last_checked_at: string | null;
}

export interface EnvironmentIn {
  name: string;
  slug: string;
  kind: EnvironmentKind;
  sort_order?: number;
  tag_values?: string[];
}

export interface ProjectIn {
  name: string;
  slug: string;
  description?: string;
  tag_values?: string[];
  environments?: EnvironmentIn[];
}

export interface HealthReason {
  signal: "resource_health" | "state" | "metric";
  severity: HealthStatus;
  message: string;
  metric?: string;
  label?: string;
  unit?: string | null;
  value?: number;
  operator?: string;
  threshold?: number | null;
  window_minutes?: number;
}

export interface HealthMetricReading {
  metric: string;
  label: string;
  unit: string | null;
  value: number;
  status: HealthStatus;
  window_minutes: number;
}

export interface Resource {
  id: string;
  azure_id: string;
  name: string;
  resource_type: string;
  type_display_name: string;
  category: string;
  kind: string | null;
  sku: string | null;
  location: string | null;
  subscription_id: string;
  subscription_name: string | null;
  resource_group: string;
  tags: Record<string, string>;
  monitor_key: string | null;
  project_id: string | null;
  project_name: string | null;
  environment_id: string | null;
  environment_name: string | null;
  assignment_source: string;
  health_status: HealthStatus;
  health_reasons: HealthReason[];
  health_evaluated_at: string | null;
  /** Latest reading of each health-rule metric, most important first. */
  health_metrics: HealthMetricReading[];
  active_alerts: number;
  azure_availability_state: string | null;
  last_seen_at: string | null;
  first_seen_at: string | null;
  dashboard_id: string | null;
}

export interface ResourceDetail extends Resource {
  properties: Record<string, unknown>;
  related: Record<string, string | null>;
  summary_metrics: string[];
  portal_url: string;
}

export interface FacetValue {
  value: string;
  label: string;
  count: number;
}

export interface ResourceFacets {
  resource_types: FacetValue[];
  locations: FacetValue[];
  resource_groups: FacetValue[];
  subscriptions: FacetValue[];
  health: FacetValue[];
}

export interface MonitorInfo {
  key: string;
  display_name: string;
  category: string;
  resource_types: string[];
  metrics: { key: string; label: string; unit: string; aggregation: string }[];
}

export interface MetricPointOut {
  timestamp: string;
  value: number | null;
}

export interface MetricSeriesOut {
  name: string;
  dimensions: Record<string, string>;
  points: MetricPointOut[];
}

export interface MetricOut {
  key: string;
  label: string;
  unit: string;
  aggregation: string;
  interval_seconds: number;
  series: MetricSeriesOut[];
  summary: { avg?: number | null; min?: number | null; max?: number | null; sum?: number | null; latest?: number | null };
  source_resource_id: string | null;
  unavailable_reason: string | null;
  unavailable_message: string | null;
  is_mock: boolean;
}

export interface MetricsResponse {
  resource_id: string;
  start: string;
  end: string;
  metrics: MetricOut[];
}

export interface Widget {
  id: string;
  position: number;
  section: string;
  widget_type: string;
  title: string;
  width: number;
  config: Record<string, unknown>;
}

export interface WidgetIn {
  section: string;
  widget_type: string;
  title: string;
  width: number;
  config: Record<string, unknown>;
}

export interface MetricDefinition {
  key: string;
  label: string;
  unit: string;
  aggregation: string;
  split_by: string | null;
  target: string;
  description: string;
}

export interface DashboardSummary {
  id: string;
  name: string;
  description: string;
  kind: string;
  resource_id: string | null;
  template_version: number | null;
  is_customized: boolean;
  updated_at: string;
  resource_type: string | null;
  type_display_name: string | null;
  project_name: string | null;
  environment_name: string | null;
  health_status: HealthStatus | null;
}

export interface Dashboard extends DashboardSummary {
  widgets: Widget[];
  sections: string[];
}

export interface Alert {
  id: string;
  rule_id: string | null;
  resource_id: string;
  resource_name: string | null;
  resource_type: string | null;
  type_display_name: string | null;
  project_id: string | null;
  project_name: string | null;
  environment_id: string | null;
  environment_name: string | null;
  source: string;
  severity: Severity;
  status: AlertStatus;
  title: string;
  metric_name: string | null;
  current_value: number | null;
  threshold: number | null;
  operator: string | null;
  started_at: string;
  last_evaluated_at: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface AlertEvent {
  id: string;
  event_type: string;
  message: string;
  value: number | null;
  actor_user_id: string | null;
  created_at: string;
}

export interface AlertDetail extends Alert {
  events: AlertEvent[];
}

export type Operator = "gt" | "gte" | "lt" | "lte";

export interface AlertRuleIn {
  name: string;
  description?: string;
  enabled: boolean;
  monitor_key: string;
  metric_name: string;
  aggregation: "Average" | "Total" | "Maximum" | "Minimum" | "Count";
  operator: Operator;
  threshold: number;
  severity: Severity;
  window_minutes: number;
  resource_id?: string | null;
  project_id?: string | null;
  environment_id?: string | null;
  notification_channel_ids: string[];
}

export interface AlertRule extends AlertRuleIn {
  id: string;
  description: string;
  created_at: string;
}

export interface NotificationChannel {
  id: string;
  name: string;
  channel_type: "webhook" | "teams" | "slack" | "email";
  enabled: boolean;
  secret_ref: string | null;
  config: Record<string, string | string[]>;
  created_at: string;
}

export interface HealthRule {
  monitor_key: string;
  monitor_name: string;
  metric_name: string;
  metric_label: string;
  unit: string;
  operator: string;
  window_minutes: number;
  default_warning: number | null;
  default_critical: number | null;
  warning_threshold: number | null;
  critical_threshold: number | null;
  enabled: boolean;
  overridden: boolean;
}

export interface SubscriptionOut {
  id: string;
  subscription_id: string;
  display_name: string;
  tenant_id: string;
  state: string;
  resource_count: number;
  last_synced_at: string | null;
}

export interface SyncStep {
  key: string;
  label: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  detail: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface SyncRun {
  id: string;
  connection_id: string;
  trigger: string;
  status: "queued" | "running" | "succeeded" | "failed";
  steps: SyncStep[];
  stats: Record<string, number>;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
}

export interface Connection {
  /** Connected to the built-in demo estate (synthetic data). */
  is_demo?: boolean;
  id: string;
  name: string;
  tenant_id: string;
  auth_method: string;
  status: "pending" | "connected" | "error" | "disabled";
  sync_enabled: boolean;
  last_sync_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  default_project_id: string | null;
  default_environment_id: string | null;
  created_at: string;
  subscriptions: SubscriptionOut[];
  resource_count: number;
  latest_run: SyncRun | null;
}

export interface ConnectionIn {
  name: string;
  tenant_id: string;
  subscription_ids: string[];
  auth_method?: "managed_identity" | "workload_identity" | "developer";
  default_project_id?: string | null;
  default_environment_id?: string | null;
}

export interface ConnectionCreated {
  connection: Connection;
  sync_run: SyncRun;
}

export interface PlatformIdentity {
  provider: string;
  auth_methods: string[];
  client_id: string | null;
  home_tenant_id: string | null;
  required_roles: { role: string; scope: string; purpose: string }[];
  is_mock: boolean;
}

export interface AvailableSubscription {
  subscription_id: string;
  display_name: string;
  state: string;
}

export interface LogTarget {
  resource_id: string;
  project_id: string | null;
  environment_id: string | null;
  name: string;
  resource_type: string;
  type_display_name: string;
  project_name: string | null;
  environment_name: string | null;
  query_count: number;
}

export interface PredefinedQuery {
  key: string;
  title: string;
  description: string;
  category: string;
  kql: string;
  visualization: "table" | "timechart" | string;
  target: string;
  supports_severity: boolean;
}

export interface LogQueryIn {
  resource_id: string;
  query_key?: string | null;
  kql?: string | null;
  time_range: TimeRangePreset;
  start?: string | null;
  end?: string | null;
  search?: string | null;
  severities?: string[];
}

export interface LogQueryResult {
  resource_id: string;
  executed_against: string;
  query: string;
  columns: { name: string; type: string }[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  partial_error: string | null;
  visualization: string;
  is_mock: boolean;
  start: string;
  end: string;
}

export interface SearchHit {
  kind: "project" | "environment" | "resource" | "alert" | "logs" | "subscription";
  id: string;
  title: string;
  subtitle: string;
  url: string;
  health_status?: HealthStatus | null;
  project_name?: string | null;
  environment_name?: string | null;
  type_display_name?: string | null;
  severity?: Severity | null;
}

export interface SearchResult {
  query: string;
  hits: SearchHit[];
}

export interface ComparisonRow {
  monitor_key: string;
  monitor_name: string;
  metric: string;
  label: string;
  unit: string;
  rollup: string;
  values: Record<string, number | null>;
  resource_counts: Record<string, number>;
}

export interface Comparison {
  project_id: string;
  environments: { id: string; name: string; kind: string; slug: string }[];
  rows: ComparisonRow[];
  start: string;
  end: string;
  is_mock: boolean;
}

export type UserStatus = "pending" | "active" | "suspended" | "deactivated";
export type RoleKey = "super_admin" | "admin" | "operator" | "viewer";

export interface UserOut {
  id: string;
  email: string | null;
  display_name: string | null;
  first_name: string | null;
  last_name: string | null;
  role_key: RoleKey;
  role_managed_by_entra: boolean;
  status: UserStatus;
  last_login_at: string | null;
  invited_at: string | null;
  invitation_expires_at: string | null;
  activated_at: string | null;
  deactivated_at: string | null;
  created_at: string;
  created_by_name: string | null;
}

/** Returned only to user administrators: includes the Entra identity binding. */
export interface UserDetail extends UserOut {
  entra_object_id: string | null;
  entra_tenant_id: string;
}

export interface UserInvite {
  email: string;
  role_key: RoleKey;
  display_name?: string | null;
}

export interface RoleOut {
  key: string;
  name: string;
  description: string;
  permissions: string[];
}

export interface AuditEntry {
  id: string;
  user_id: string | null;
  actor: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  result: "success" | "failure" | "denied";
  ip_address: string | null;
  request_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ActivityEntry {
  azure_id?: string;
  change_type?: string;
  changed_at?: string | null;
  changed_by?: string | null;
  operation?: string | null;
  error?: string;
  message?: string;
}

export interface OverviewEnvironment {
  id: string;
  name: string;
  slug: string;
  kind: string;
  status: HealthStatus;
  counts: HealthCounts;
  active_alerts: number;
  last_checked_at: string | null;
}

export interface Overview {
  is_mock: boolean;
  /** When the API built this response. */
  generated_at: string;
  /** Most recent Azure synchronisation across connections. */
  last_synced_at: string | null;
  /** Environments by their worst monitored-resource status. */
  environment_health: Record<HealthStatus, number>;
  totals: {
    projects: number;
    environments: number;
    subscriptions: number;
    connections: number;
    resources: number;
    monitored_resources: number;
    /** Discovered but without a dedicated monitor (NICs, DNS zones, ...). */
    inventory_resources: number;
    /** Monitored resources without a project. */
    unassigned_resources: number;
  };
  /** Monitored resources that are critical or warning, critical first (max 12). */
  needs_attention: {
    id: string;
    name: string;
    type_display_name: string;
    project_name: string | null;
    environment_name: string | null;
    health_status: "critical" | "warning";
    reason: string;
  }[];
  health: HealthCounts;
  alerts: { active: number; by_severity: Partial<Record<Severity, number>> };
  project_health: {
    id: string;
    name: string;
    slug: string;
    description: string;
    status: HealthStatus;
    counts: HealthCounts;
    active_alerts: number;
    last_checked_at: string | null;
    environments: OverviewEnvironment[];
  }[];
  recent_alerts: Alert[];
  resource_types: { label: string; count: number; monitored: boolean; counts: Record<HealthStatus, number> }[];
  service_health: {
    id: string;
    title: string;
    event_type: string;
    status: string;
    level: string | null;
    services: string[];
    /** At most 4: regions we have resources in, or Global. */
    regions: string[];
    region_count: number;
    relevant: boolean;
    last_update: string | null;
  }[];
  recent_changes: {
    azure_id: string;
    change_type: string;
    changed_at: string | null;
    changed_by: string | null;
    operation: string | null;
    resource_id: string | null;
    resource_name: string;
    type_display_name: string | null;
  }[];
  feed_errors: { connection: string; code: string; message: string }[];
}

/** One health-rule metric on the Live page: the last hour at 1-minute resolution. */
export interface LiveMetric {
  key: string;
  label: string;
  unit: string;
  /** Most recent non-empty minute. */
  latest: number | null;
  latest_at: string | null;
  /** The health rule's window reduced the same way health evaluation does (e.g. 15-minute average). */
  window_value: number | null;
  window_minutes: number;
  reducer: "avg" | "sum" | "max" | "min";
  operator: Operator;
  warning: number | null;
  critical: number | null;
  /** ``window_value`` against the thresholds; ``unknown`` when there is no data. */
  status: HealthStatus;
  points: { timestamp: string; value: number | null }[];
  unavailable_reason: string | null;
}

export interface LiveResource {
  id: string;
  name: string;
  type_display_name: string;
  project_id: string | null;
  project_name: string | null;
  environment_id: string | null;
  environment_name: string | null;
  health_status: HealthStatus;
  health_evaluated_at: string | null;
  active_alerts: number;
  metrics: LiveMetric[];
}

export interface LiveEnvironment {
  project_id: string;
  project_name: string;
  environment_id: string;
  environment_name: string;
  kind: string;
  status: HealthStatus;
  counts: HealthCounts;
  active_alerts: number;
  last_checked_at: string | null;
}

export interface Live {
  is_mock: boolean;
  generated_at: string;
  window_minutes: number;
  interval_seconds: number;
  /** Monitored resources in scope by stored health status. */
  health: HealthCounts;
  alerts: { active: number; by_severity: Partial<Record<Severity, number>> };
  environments: LiveEnvironment[];
  /** Worst health first, at most 24. */
  resources: LiveResource[];
  /** All monitored resources in scope (``resources`` may be a subset). */
  resources_total: number;
  recent_alerts: Alert[];
}
