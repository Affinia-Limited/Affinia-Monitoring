import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ScrollText, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { AlertsExplorer } from "@/components/AlertsExplorer";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ConfirmButton, KpiCard, PageHeader } from "@/components/common";
import { EnvironmentResourceTable } from "@/components/EnvironmentResourceTable";
import { Freshness } from "@/components/Freshness";
import { HealthSummary, HealthText } from "@/components/health";
import { EnvironmentNav } from "@/components/projects/EnvironmentNav";
import { formatReading, keyReading, shortReason, topReason } from "@/components/resourceSignals";
import { SeverityBadge, TimeAgo } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock, TableSkeleton } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { AlertDetailDrawer } from "@/pages/Alerts/AlertDetailDrawer";
import type { EnvironmentSummary, Project } from "@/types/api";
import { cn } from "@/utils/cn";
import { paths } from "@/utils/paths";

const TABS = ["overview", "resources", "alerts", "logs"] as const;
type Tab = (typeof TABS)[number];

const ISSUE_LIMIT = 8;

/** Only resources that need attention, worst first, each with the reason and a way in. */
function IssuesCard({ projectId, environment }: { projectId: string; environment: EnvironmentSummary }) {
  const filters = { project_id: projectId, environment_id: environment.id, health: "critical,warning", monitored_only: true };
  const query = useQuery({
    queryKey: ["resources", { ...filters, page_size: ISSUE_LIMIT }],
    queryFn: () => endpoints.resources({ ...filters, page_size: ISSUE_LIMIT, sort: "health" }),
    refetchInterval: 60_000,
  });
  const total = query.data?.total ?? 0;
  return (
    <Card>
      <CardHeader title="Issues" description="Resources currently outside their health thresholds" />
      {query.isLoading ? (
        <TableSkeleton rows={3} label="Loading issues" />
      ) : query.isError ? (
        <CardContent>
          <ErrorState error={query.error} title={`Unable to load ${environment.name} issues.`} onRetry={() => void query.refetch()} />
        </CardContent>
      ) : total === 0 ? (
        <CardContent>
          <div className="flex items-center gap-3 py-2">
            <CheckCircle2 className="size-6 text-healthy" aria-hidden="true" />
            <div>
              <p className="text-sm font-medium">No critical issues</p>
              <p className="text-sm text-muted-foreground">
                {environment.health.total ? "Everything looks healthy." : "No monitored resources have been checked in this environment yet."}
              </p>
            </div>
          </div>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {query.data?.items.map((r) => {
            const reason = topReason(r.health_reasons);
            const reading = keyReading(r);
            return (
              <li key={r.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <HealthText status={r.health_status} />
                    <Link to={paths.resource(r.id)} className="truncate text-sm font-medium hover:underline">
                      {r.name}
                    </Link>
                    <span className="text-xs text-muted-foreground">{r.type_display_name}</span>
                  </div>
                  <p className={cn("mt-1 text-sm", r.health_status === "critical" ? "text-critical" : "text-warning")}>
                    {reason ? shortReason(reason) : reading ? `${reading.label} ${formatReading(reading)}` : "Health signals outside thresholds"}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Checked <TimeAgo value={r.health_evaluated_at} />
                    {r.active_alerts ? ` · ${r.active_alerts} active alert${r.active_alerts === 1 ? "" : "s"}` : ""}
                  </p>
                </div>
                <Button asChild variant="outline" size="sm">
                  <Link to={paths.resource(r.id)} aria-label={`View resource ${r.name}`}>
                    View resource
                  </Link>
                </Button>
              </li>
            );
          })}
          {total > ISSUE_LIMIT ? (
            <li className="px-5 py-2 text-xs text-muted-foreground">
              and {total - ISSUE_LIMIT} more. Open the Resources tab and filter by Critical or Warning.
            </li>
          ) : null}
        </ul>
      )}
    </Card>
  );
}

function RecentAlerts({ projectId, environmentId, onOpenAll }: { projectId: string; environmentId: string; onOpenAll: () => void }) {
  const query = useQuery({
    queryKey: ["alerts", { status: "open", project_id: projectId, environment_id: environmentId, page_size: 5 }],
    queryFn: () => endpoints.alerts({ status: "open", project_id: projectId, environment_id: environmentId, page_size: 5 }),
    refetchInterval: 60_000,
  });
  return (
    <Card>
      <CardHeader
        title="Active alerts"
        actions={
          <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={onOpenAll}>
            View all
          </Button>
        }
      />
      {query.isLoading ? (
        <TableSkeleton rows={2} label="Loading alerts" />
      ) : query.isError ? (
        <CardContent>
          <ErrorState error={query.error} compact title="Unable to load alerts." onRetry={() => void query.refetch()} />
        </CardContent>
      ) : !query.data?.items.length ? (
        <CardContent>
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <CheckCircle2 className="size-4 text-healthy" aria-hidden="true" /> No active alerts. Everything is within its alert thresholds.
          </p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {query.data.items.map((a) => (
            <li key={a.id} className="flex items-center gap-3 px-5 py-3 text-sm">
              <SeverityBadge severity={a.severity} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{a.title}</p>
                <p className="truncate text-xs text-muted-foreground">{a.resource_name}</p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">
                <TimeAgo value={a.started_at} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function LogsPanel({ project, environment }: { project: Project; environment: EnvironmentSummary }) {
  const canLogs = usePermission(PERMISSIONS.viewLogs);
  return (
    <Card>
      <CardContent className="py-8">
        <EmptyState
          icon={<ScrollText className="size-8" />}
          title={`Logs for ${project.name} / ${environment.name}`}
          description={
            canLogs
              ? "Run predefined Log Analytics and Application Insights queries against any resource in this environment."
              : "Your role does not include log access. Ask an administrator if you need it."
          }
          action={
            canLogs ? (
              <Button asChild>
                <Link to={paths.logs(project.id, environment.id)}>
                  Open logs <ArrowRight />
                </Link>
              </Button>
            ) : null
          }
        />
      </CardContent>
    </Card>
  );
}

export function EnvironmentPage() {
  const { projectId = "", environmentId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const canManage = usePermission(PERMISSIONS.manageProjects);
  const [alertId, setAlertId] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["project", projectId], queryFn: () => endpoints.project(projectId), refetchInterval: 60_000 });
  const requested = params.get("tab");
  const tab: Tab = TABS.includes(requested as Tab) ? (requested as Tab) : "overview";
  const setTab = (next: string) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === "overview") p.delete("tab");
        else p.set("tab", next);
        return p;
      },
      { replace: true },
    );

  if (query.isLoading) return <LoadingBlock label="Loading environment" />;
  if (query.isError || !query.data) {
    return (
      <>
        <Breadcrumbs items={[{ label: "Projects", to: paths.projects() }, { label: "Environment" }]} />
        <ErrorState error={query.error} title="Unable to load this environment." onRetry={() => void query.refetch()} />
      </>
    );
  }
  const project = query.data;
  const environment = project.environments.find((e) => e.id === environmentId);
  if (!environment) {
    return (
      <>
        <Breadcrumbs items={[{ label: "Projects", to: paths.projects() }, { label: project.name, to: paths.project(project.id) }, { label: "Not found" }]} />
        <Card>
          <EmptyState
            title="Environment not found"
            description="It may have been removed from this project."
            action={
              <Link className="text-primary hover:underline" to={paths.project(project.id)}>
                Back to {project.name}
              </Link>
            }
          />
        </Card>
      </>
    );
  }
  const counts = environment.health;

  return (
    <>
      <Breadcrumbs
        items={[
          { label: "Projects", to: paths.projects() },
          { label: project.name, to: paths.project(project.id) },
          { label: environment.name },
        ]}
      />
      <PageHeader
        title={`${project.name} / ${environment.name}`}
        badge={<HealthText status={counts.total ? environment.status : "unknown"} className="ml-1" />}
        actions={
          canManage ? (
            <ConfirmButton
              title={`Delete environment ${environment.name}?`}
              description="Resources in this environment stay assigned to the project without an environment."
              confirmLabel="Delete environment"
              onConfirm={async () => {
                await endpoints.deleteEnvironment(project.id, environment.id);
                await qc.invalidateQueries({ queryKey: ["project", project.id] });
                await qc.invalidateQueries({ queryKey: ["projects"] });
                navigate(paths.project(project.id));
              }}
            >
              <Trash2 /> Delete environment
            </ConfirmButton>
          ) : null
        }
      />
      <Freshness updatedAt={query.dataUpdatedAt} checkedAt={environment.last_checked_at} className="-mt-4 mb-5" />
      <EnvironmentNav project={project} />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label={`${environment.name} views`}>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="resources">Resources</TabsTrigger>
          <TabsTrigger value="alerts">
            Alerts{environment.active_alerts ? <span className="ml-1.5 rounded-full bg-critical/10 px-1.5 text-xs text-critical">{environment.active_alerts}</span> : null}
          </TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="space-y-6">
            <section aria-label="Environment summary" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
              <KpiCard label="Resources" value={counts.total} hint={counts.unknown ? `${counts.unknown} not checked` : undefined} />
              <KpiCard label="Healthy" value={counts.healthy} tone={counts.healthy ? "healthy" : undefined} />
              <KpiCard label="Warning" value={counts.warning} tone={counts.warning ? "warning" : undefined} />
              <KpiCard label="Critical" value={counts.critical} tone={counts.critical ? "critical" : undefined} />
              <KpiCard label="Active alerts" value={environment.active_alerts} tone={environment.active_alerts ? "critical" : undefined} />
            </section>
            <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-3">
              <div className="space-y-6 xl:col-span-2">
                <IssuesCard projectId={project.id} environment={environment} />
                <RecentAlerts projectId={project.id} environmentId={environment.id} onOpenAll={() => setTab("alerts")} />
              </div>
              <Card>
                <CardContent className="pt-5">
                  <HealthSummary counts={counts} title={`${environment.name} health`} />
                  <Button variant="outline" size="sm" className="mt-5 w-full" onClick={() => setTab("resources")}>
                    View all resources
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>
        <TabsContent value="resources">
          <EnvironmentResourceTable projectId={project.id} environmentId={environment.id} />
        </TabsContent>
        <TabsContent value="alerts">
          <AlertsExplorer projectId={project.id} environmentId={environment.id} onSelect={(a) => setAlertId(a.id)} />
        </TabsContent>
        <TabsContent value="logs">
          <LogsPanel project={project} environment={environment} />
        </TabsContent>
      </Tabs>
      <AlertDetailDrawer alertId={alertId} onClose={() => setAlertId(null)} />
    </>
  );
}
