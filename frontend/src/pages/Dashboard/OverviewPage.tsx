import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Cloud } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { KpiCard } from "@/components/common";
import { HealthDot, SeverityBadge, TimeAgo } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Freshness } from "@/components/Freshness";
import { AsOfLastCheck, LiveMark } from "@/components/live";
import { shortReason, topReason } from "@/components/resourceSignals";
import { ProjectCard, ProjectCardSkeleton } from "@/components/projects/ProjectCard";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useLiveResources } from "@/hooks/useLiveResources";
import { PERMISSIONS, useMe, usePermission } from "@/hooks/useMe";
import { useRefreshInterval } from "@/stores/live";
import type { Overview, Project } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatDateTime } from "@/utils/format";
import { firstName, greeting } from "@/utils/paths";

const STATUS_ORDER: Record<string, number> = { critical: 0, warning: 1, healthy: 2, unknown: 3 };

/** Projects that need action first, then alphabetical. */
function sortByAttention(projects: Project[]): Project[] {
  const rank = (p: Project) => STATUS_ORDER[p.health.total ? p.status : "unknown"] ?? 9;
  return [...projects].sort((a, b) => rank(a) - rank(b) || b.active_alerts - a.active_alerts || a.name.localeCompare(b.name));
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
}

function SectionLink({ to, children }: { to: string; children: string }) {
  return (
    <Button asChild variant="ghost" size="sm" className="text-muted-foreground">
      <Link to={to}>{children}</Link>
    </Button>
  );
}

function NeedsAttention({ items }: { items: Overview["needs_attention"] }) {
  const { byId } = useLiveResources(items.map((r) => r.id));
  return (
    <Card>
      <CardHeader title="Needs attention" actions={items.length ? <SectionLink to="/resources?view=attention">View in Resources</SectionLink> : null} />
      {items.length === 0 ? (
        <CardContent>
          <p className="py-2 text-sm text-muted-foreground">Everything monitored is healthy. Nothing needs your attention right now.</p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {items.map((r) => {
            const state = byId[r.id];
            const status = state?.status ?? r.health_status;
            const live = state ? topReason(state.reasons) : null;
            return (
            <li key={r.id} className="grid grid-cols-12 items-center gap-x-4 gap-y-1 px-5 py-3 text-sm">
              <div className="col-span-12 flex min-w-0 items-center gap-2.5 md:col-span-4">
                <HealthDot status={status} />
                <Link to={`/resources/${r.id}`} className="truncate font-medium hover:underline">
                  {r.name}
                </Link>
              </div>
              <div className="col-span-6 truncate text-muted-foreground md:col-span-2">{r.type_display_name}</div>
              <div className="col-span-6 truncate text-muted-foreground md:col-span-2">
                {r.project_name ? `${r.project_name} / ${r.environment_name ?? "-"}` : "Unassigned"}
              </div>
              <div className={cn("col-span-12 flex items-center gap-2 md:col-span-4", status === "critical" ? "text-critical" : status === "warning" ? "text-warning" : "text-healthy")}>
                <span className="min-w-0">{state ? (live ? shortReason(live) : "Back within thresholds") : r.reason}</span>
                {state ? <LiveMark className="shrink-0" /> : null}
              </div>
            </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function ProjectsSection() {
  const refetchInterval = useRefreshInterval(60_000);
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, refetchInterval });
  const canManage = usePermission(PERMISSIONS.manageProjects);
  return (
    <section aria-labelledby="overview-projects">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 id="overview-projects" className="text-base font-semibold">
          Projects
        </h2>
        <SectionLink to="/projects">View all projects</SectionLink>
      </div>
      {projects.isLoading ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <ProjectCardSkeleton key={i} />
          ))}
        </div>
      ) : projects.isError ? (
        <ErrorState error={projects.error} title="Unable to load projects." onRetry={() => void projects.refetch()} />
      ) : (projects.data ?? []).length === 0 ? (
        <Card>
          <EmptyState
            title="No projects yet"
            description="Add your first Azure project to start monitoring by application and environment."
            action={
              canManage ? (
                <Button asChild>
                  <Link to="/projects?new=1">Add project</Link>
                </Button>
              ) : null
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {sortByAttention(projects.data ?? []).map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}
    </section>
  );
}

function ActiveAlerts({ alerts, total }: { alerts: Overview["recent_alerts"]; total: number }) {
  return (
    <Card>
      <CardHeader title="Active alerts" actions={<SectionLink to="/alerts">View all</SectionLink>} />
      {alerts.length === 0 ? (
        <CardContent>
          <p className="text-sm text-muted-foreground">No active alerts.</p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {alerts.slice(0, 5).map((a) => (
            <li key={a.id} className="flex items-center gap-3 px-5 py-3 text-sm">
              <SeverityBadge severity={a.severity} />
              <div className="min-w-0 flex-1">
                <Link to={`/resources/${a.resource_id}`} className="block truncate font-medium hover:underline" title={a.title}>
                  {a.title}
                </Link>
                <p className="truncate text-xs text-muted-foreground">
                  {[a.project_name, a.environment_name].filter(Boolean).join(" / ") || "Unassigned"}
                </p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">
                <TimeAgo value={a.started_at} />
              </span>
            </li>
          ))}
          {total > 5 ? <li className="px-5 py-2 text-xs text-muted-foreground">and {total - 5} more</li> : null}
        </ul>
      )}
    </Card>
  );
}

function regionsLabel(e: Overview["service_health"][number]): string {
  const shown = e.regions[0] ?? "All regions";
  const others = Math.max(0, e.region_count - 1);
  return others ? `${shown} +${others} region${others === 1 ? "" : "s"}` : shown;
}

function ServiceHealth({ events }: { events: Overview["service_health"] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader title="Azure Service Health" />
      {events.length === 0 ? (
        <CardContent>
          <p className="text-sm text-muted-foreground">No Service Health events affecting your regions.</p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {events.map((e) => {
            const expanded = open === e.id;
            return (
              <li key={e.id}>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : e.id)}
                  className="flex w-full items-start gap-3 px-5 py-3 text-left text-sm hover:bg-muted/40"
                >
                  <div className="min-w-0 flex-1">
                    <p className={cn("font-medium", !expanded && "line-clamp-1")}>{e.title}</p>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {e.services.join(", ") || "Azure"} · {regionsLabel(e)}
                    </p>
                  </div>
                  <Badge tone={e.status.toLowerCase() === "active" ? (e.level === "Warning" ? "warning" : "info") : "neutral"}>{e.status}</Badge>
                  <ChevronDown className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-180")} />
                </button>
                {expanded ? (
                  <div className="px-5 pb-3 text-xs text-muted-foreground">
                    {e.event_type.replace(/([a-z])([A-Z])/g, "$1 $2")}
                    {e.level ? ` · ${e.level}` : ""} · updated {formatDateTime(e.last_update)}
                    {e.regions.length ? ` · ${e.regions.join(", ")}${e.region_count > e.regions.length ? ` and ${e.region_count - e.regions.length} more` : ""}` : ""}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function RecentChanges({ changes }: { changes: Overview["recent_changes"] }) {
  return (
    <Card>
      <CardHeader title="Recent changes" description="Azure Resource Graph change history" />
      {changes.length === 0 ? (
        <CardContent>
          <p className="text-sm text-muted-foreground">No recent changes to monitored resources.</p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {changes.map((c, i) => (
            <li key={`${c.azure_id}-${i}`} className="flex flex-wrap items-center gap-x-4 gap-y-0.5 px-5 py-3 text-sm">
              {c.resource_id ? (
                <Link to={`/resources/${c.resource_id}`} className="min-w-40 truncate font-medium hover:underline">
                  {c.resource_name}
                </Link>
              ) : (
                <span className="min-w-40 truncate font-medium">{c.resource_name}</span>
              )}
              <span className="text-muted-foreground">{c.type_display_name}</span>
              <span className="text-muted-foreground">{c.change_type}</span>
              {c.changed_by ? <span className="text-muted-foreground">by {c.changed_by}</span> : null}
              <span className="ml-auto text-xs text-muted-foreground">
                <TimeAgo value={c.changed_at} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function OverviewPage() {
  const refetchInterval = useRefreshInterval(60_000);
  const query = useQuery({ queryKey: ["overview"], queryFn: endpoints.overview, refetchInterval });
  const { data: me } = useMe();
  if (query.isLoading) return <OverviewSkeleton />;
  if (query.isError || !query.data) {
    return <ErrorState error={query.error} title="Unable to load the overview." onRetry={() => void query.refetch()} className="mt-6" />;
  }
  const o = query.data;
  const name = firstName(me?.display_name);

  if (o.totals.connections === 0) {
    return (
      <Card className="mt-6">
        <EmptyState
          icon={<Cloud className="size-10" />}
          title="Connect your first Azure subscription"
          description="Resources are discovered with Azure Resource Graph and dashboards are built automatically. No passwords or client secrets are needed."
          action={
            <Button asChild>
              <Link to="/azure-connections">Go to Azure Connections</Link>
            </Button>
          }
        />
      </Card>
    );
  }

  const envs = o.environment_health;
  const notChecked = envs.unknown ?? 0;
  return (
    <div className="space-y-8">
      <header>
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Azure Monitoring</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          {greeting()}
          {name ? `, ${name}` : ""}
        </h1>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="rounded-full border border-border px-2.5 py-0.5 text-xs font-medium">All projects</span>
          <Freshness updatedAt={query.dataUpdatedAt} syncedAt={o.last_synced_at} />
        </div>
      </header>

      <section aria-label="Status summary" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard
          label="Projects"
          value={o.totals.projects}
          hint={`${plural(o.totals.environments, "environment")}${notChecked ? `, ${notChecked} not checked` : ""}`}
        />
        <KpiCard label="Healthy" value={envs.healthy ?? 0} tone={envs.healthy ? "healthy" : undefined} hint={plural(envs.healthy ?? 0, "environment")} />
        <KpiCard label="Warnings" value={envs.warning ?? 0} tone={envs.warning ? "warning" : undefined} hint={plural(envs.warning ?? 0, "environment")} />
        <KpiCard label="Critical" value={envs.critical ?? 0} tone={envs.critical ? "critical" : undefined} hint={plural(envs.critical ?? 0, "environment")} />
        <KpiCard
          label="Active alerts"
          value={o.alerts.active}
          tone={o.alerts.active ? "critical" : undefined}
          hint={
            o.alerts.active ? (
              <Link to="/alerts" className="hover:underline">
                View alerts
              </Link>
            ) : (
              "Nothing firing"
            )
          }
        />
      </section>
      <AsOfLastCheck className="-mt-5" />

      {o.feed_errors.length > 0 ? (
        <div role="status" className="rounded-lg border border-warning/30 bg-warning/5 px-5 py-3 text-sm">
          <p className="font-medium">Some Azure information could not be refreshed.</p>
          {o.feed_errors.map((e) => (
            <p key={e.connection} className="text-muted-foreground">
              {e.connection}: {e.message}
            </p>
          ))}
        </div>
      ) : null}

      <NeedsAttention items={o.needs_attention} />
      <ProjectsSection />
      {o.totals.unassigned_resources > 0 ? (
        <p className="rounded-lg border border-border bg-card px-5 py-3 text-sm text-muted-foreground">
          {plural(o.totals.unassigned_resources, "monitored resource")} {o.totals.unassigned_resources === 1 ? "is" : "are"} not assigned to a
          project.{" "}
          <Link to="/resources?view=unassigned" className="font-medium text-primary hover:underline">
            Review unassigned resources
          </Link>
        </p>
      ) : null}
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <ActiveAlerts alerts={o.recent_alerts} total={o.alerts.active} />
        <ServiceHealth events={o.service_health} />
      </div>
      <RecentChanges changes={o.recent_changes} />
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-8" role="status" aria-label="Loading overview">
      <div className="space-y-2">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-7 w-64" />
        <Skeleton className="h-4 w-80" />
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <ProjectCardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}
