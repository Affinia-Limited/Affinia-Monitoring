import type {
  ActivityEntry,
  Alert,
  AlertDetail,
  AlertRule,
  AlertPlan,
  AlertRuleIn,
  AlertTemplate,
  AlertTemplateAssignment,
  EffectiveCoverage,
  AlertTemplateAssignmentIn,
  AuditEntry,
  AvailableSubscription,
  Comparison,
  Connection,
  ConnectionCreated,
  ConnectionIn,
  Dashboard,
  DashboardSummary,
  EnvironmentIn,
  EnvironmentOut,
  HealthRule,
  LogQueryIn,
  LogQueryResult,
  LiveResources,
  LogTarget,
  Me,
  MetricDefinition,
  MetricsResponse,
  MonitorInfo,
  NotificationChannel,
  EmailList,
  EmailListIn,
  EmailStatus,
  TeamsChannel,
  TeamsChannelIn,
  TeamsSetup,
  TemplateRule,
  TemplateRuleIn,
  Overview,
  Page,
  PlatformIdentity,
  PredefinedQuery,
  Project,
  ProjectIn,
  Resource,
  ResourceDetail,
  ResourceFacets,
  RoleKey,
  RoleOut,
  SearchResult,
  SubscriptionOut,
  SyncRun,
  AccessGrantIn,
  AssignableResource,
  AssignableScope,
  UserDetail,
  UserInvite,
  UserOut,
  WidgetIn,
} from "@/types/api";
import { get, send } from "./client";

export type Params = Record<string, string | number | boolean | undefined | null>;
export type UserStatusAction = "suspend" | "reactivate" | "deactivate";

export const endpoints = {
  me: () => get<Me>("/auth/me"),
  startSession: () => send<Me>("post", "/auth/session"),

  overview: () => get<Overview>("/overview"),
  liveResources: (ids: string[]) => get<LiveResources>("/live/resources", { ids: ids.join(",") }),
  search: (q: string) => get<SearchResult>("/search", { q }),

  projects: () => get<Project[]>("/projects"),
  project: (id: string) => get<Project>(`/projects/${id}`),
  createProject: (body: ProjectIn) => send<Project>("post", "/projects", body),
  updateProject: (id: string, body: Partial<Pick<Project, "name" | "description" | "tag_values">>) =>
    send<Project>("patch", `/projects/${id}`, body),
  deleteProject: (id: string) => send<void>("delete", `/projects/${id}`),
  createEnvironment: (projectId: string, body: EnvironmentIn) =>
    send<EnvironmentOut>("post", `/projects/${projectId}/environments`, body),
  deleteEnvironment: (projectId: string, envId: string) =>
    send<void>("delete", `/projects/${projectId}/environments/${envId}`),
  comparison: (projectId: string, params: Params) => get<Comparison>(`/projects/${projectId}/comparison`, params),

  resources: (params: Params) => get<Page<Resource>>("/resources", params),
  facets: (params: Params) => get<ResourceFacets>("/resources/facets", params),
  monitors: () => get<MonitorInfo[]>("/resources/monitors"),
  resource: (id: string) => get<ResourceDetail>(`/resources/${id}`),
  metrics: (id: string, params: Params) => get<MetricsResponse>(`/resources/${id}/metrics`, params),
  related: (id: string, relation: string) => get<Resource[]>(`/resources/${id}/related/${relation}`),
  assign: (id: string, body: { project_id: string | null; environment_id: string | null }) =>
    send<Resource>("put", `/resources/${id}/assignment`, body),
  evaluateHealth: (id: string) => send<Resource>("post", `/resources/${id}/health/evaluate`),
  activity: (id: string) => get<ActivityEntry[]>(`/resources/${id}/activity`),

  dashboards: (params: Params) => get<DashboardSummary[]>("/dashboards", params),
  dashboard: (id: string) => get<Dashboard>(`/dashboards/${id}`),
  dashboardForResource: (resourceId: string) => get<Dashboard>(`/dashboards/by-resource/${resourceId}`),
  resetDashboard: (id: string) => send<Dashboard>("post", `/dashboards/${id}/reset`),
  updateDashboard: (id: string, body: { name?: string; widgets?: WidgetIn[] }) => send<Dashboard>("patch", `/dashboards/${id}`, body),
  metricDefinitions: (resourceId: string) => get<MetricDefinition[]>(`/resources/${resourceId}/metric-definitions`),

  logTargets: () => get<LogTarget[]>("/logs/targets"),
  logQueries: (resourceId: string) => get<PredefinedQuery[]>("/logs/queries", { resource_id: resourceId }),
  runLogQuery: (body: LogQueryIn) => send<LogQueryResult>("post", "/logs/query", body),

  alerts: (params: Params) => get<Page<Alert>>("/alerts", params),
  alert: (id: string) => get<AlertDetail>(`/alerts/${id}`),
  acknowledgeAlert: (id: string) => send<AlertDetail>("post", `/alerts/${id}/acknowledge`),
  resolveAlert: (id: string) => send<AlertDetail>("post", `/alerts/${id}/resolve`),
  alertRules: () => get<AlertRule[]>("/alert-rules"),
  createAlertRule: (body: AlertRuleIn) => send<AlertRule>("post", "/alert-rules", body),
  updateAlertRule: (id: string, body: AlertRuleIn) => send<AlertRule>("put", `/alert-rules/${id}`, body),
  deleteAlertRule: (id: string) => send<void>("delete", `/alert-rules/${id}`),
  alertTemplates: () => get<AlertTemplate[]>("/alert-templates"),
  alertTemplate: (monitorKey: string) => get<AlertTemplate>(`/alert-templates/${monitorKey}`),
  updateTemplateRule: (monitorKey: string, metric: string, body: TemplateRuleIn) =>
    send<TemplateRule>("put", `/alert-templates/${monitorKey}/rules/${metric}`, body),
  resetTemplateRule: (monitorKey: string, metric: string) =>
    send<TemplateRule>("delete", `/alert-templates/${monitorKey}/rules/${metric}`),
  templateAssignments: (params: Params = {}) => get<AlertTemplateAssignment[]>("/alert-template-assignments", params),
  effectiveCoverage: (environmentId: string) =>
    get<EffectiveCoverage>("/alert-template-assignments/effective", { environment_id: environmentId }),
  createTemplateAssignment: (body: AlertTemplateAssignmentIn) =>
    send<AlertTemplateAssignment>("post", "/alert-template-assignments", body),
  updateTemplateAssignment: (id: string, body: Pick<AlertTemplateAssignmentIn, "enabled" | "overrides" | "notification_channel_ids">) =>
    send<AlertTemplateAssignment>("patch", `/alert-template-assignments/${id}`, body),
  deleteTemplateAssignment: (id: string) => send<void>("delete", `/alert-template-assignments/${id}`),
  alertPlan: (resourceId: string) => get<AlertPlan>(`/resources/${resourceId}/alert-plan`),
  /** Run health and alert-rule evaluation now (at most once a minute). */
  evaluateAlertRules: () => send<{ status: string; message: string }>("post", "/alert-rules/evaluate"),
  channels: () => get<NotificationChannel[]>("/notification-channels"),
  createChannel: (body: Omit<NotificationChannel, "id" | "created_at">) =>
    send<NotificationChannel>("post", "/notification-channels", body),
  deleteChannel: (id: string) => send<void>("delete", `/notification-channels/${id}`),
  testChannel: (id: string) => send<{ status: string; message: string }>("post", `/notification-channels/${id}/test`),
  teamsSetup: () => get<TeamsSetup>("/notifications/teams-setup"),
  teamsChannels: () => get<TeamsChannel[]>("/notifications/teams-channels"),
  createTeamsChannel: (body: TeamsChannelIn) => send<TeamsChannel>("post", "/notifications/teams-channels", body),
  updateTeamsChannel: (id: string, body: Partial<TeamsChannelIn>) =>
    send<TeamsChannel>("patch", `/notifications/teams-channels/${id}`, body),
  deleteTeamsChannel: (id: string) => send<void>("delete", `/notifications/teams-channels/${id}`),
  emailStatus: () => get<EmailStatus>("/notifications/email-status"),
  emailLists: () => get<EmailList[]>("/notifications/email-lists"),
  createEmailList: (body: EmailListIn) => send<EmailList>("post", "/notifications/email-lists", body),
  updateEmailList: (id: string, body: Partial<EmailListIn>) => send<EmailList>("patch", `/notifications/email-lists/${id}`, body),
  deleteEmailList: (id: string) => send<void>("delete", `/notifications/email-lists/${id}`),
  testEmailList: (id: string) => send<{ status: "sent" | "failed"; message: string }>("post", `/notifications/email-lists/${id}/test`),
  healthRules: () => get<HealthRule[]>("/health-rules"),
  setHealthRule: (body: {
    monitor_key: string;
    metric_name: string;
    warning_threshold: number | null;
    critical_threshold: number | null;
    enabled: boolean;
  }) => send<HealthRule>("put", "/health-rules", body),

  identity: () => get<PlatformIdentity>("/azure/identity"),
  availableSubscriptions: (tenantId: string) =>
    get<AvailableSubscription[]>("/azure/available-subscriptions", { tenant_id: tenantId }),
  connections: () => get<Connection[]>("/azure/connections"),
  createConnection: (body: ConnectionIn) => send<ConnectionCreated>("post", "/azure/connections", body),
  updateConnection: (id: string, body: Record<string, unknown>) =>
    send<Connection>("patch", `/azure/connections/${id}`, body),
  deleteConnection: (id: string) => send<void>("delete", `/azure/connections/${id}`),
  syncConnection: (id: string) => send<SyncRun>("post", `/azure/connections/${id}/sync`),
  syncRun: (id: string) => get<SyncRun>(`/azure/sync-runs/${id}`),
  syncRuns: (connectionId: string) => get<SyncRun[]>(`/azure/connections/${connectionId}/sync-runs`),
  subscriptions: () => get<SubscriptionOut[]>("/azure/subscriptions"),

  users: (params: Params) => get<Page<UserOut>>("/users", params),
  user: (id: string) => get<UserDetail>(`/users/${id}`),
  userAudit: (id: string, params: Params) => get<Page<AuditEntry>>(`/users/${id}/audit`, params),
  inviteUser: (body: UserInvite) => send<UserDetail>("post", "/users/invite", body),
  updateUserAccess: (id: string, grants: AccessGrantIn[]) => send<UserDetail>("put", `/users/${id}/access`, { grants }),
  assignableScope: () => get<AssignableScope>("/users/assignable-scope"),
  assignableResources: (environmentId: string, params: Params) =>
    get<AssignableResource[]>(`/users/assignable-scope/environments/${environmentId}/resources`, params),
  updateUser: (id: string, body: { role_key?: RoleKey; display_name?: string }) =>
    send<UserDetail>("patch", `/users/${id}`, body),
  setUserStatus: (id: string, action: UserStatusAction) => send<UserDetail>("post", `/users/${id}/${action}`),
  /** Only for revoked (deactivated) users: erases personal data and access, keeps the audit history. */
  deleteUser: (id: string) => send<void>("delete", `/users/${id}`),
  roles: () => get<RoleOut[]>("/roles"),
  auditLogs: (params: Params) => get<Page<AuditEntry>>("/audit-logs", params),
};
