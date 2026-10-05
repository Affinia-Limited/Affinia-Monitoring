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
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import type { Overview } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatDateTime, formatRelative } from "@/utils/format";

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
}

function Headline({ o, lastSync }: { o: Overview; lastSync: string | null }) {
  const attention = o.health.critical + o.health.warning;
  const tone = o.health.critical ? "critical" : attention ? "warning" : "healthy";
  const meta = [
    plural(o.totals.projects, "project"),
    plural(o.totals.subscriptions, "subscription"),
    lastSync ? `last synchronised ${formatRelative(lastSync)}` : "not synchronised yet",
  ];
  return (
    <div className="mb-6">
      <h1 className="flex items-center gap-3 text-2xl font-semibold tracking-tight">
        <HealthDot status={tone} className="size-3" />
        {attention ? `${plural(attention, "resource")} ${attention === 1 ? "needs" : "need"} attention` : "All monitored resources are healthy"}
      </h1>
      <p className="mt-1.5 text-sm text-muted-foreground" title={lastSync ? formatDateTime(lastSync) : undefined}>
        {meta.join(" · ")}
      </p>
    </div>
  );
}

function SectionLink({ to, children }: { to: string; children: string }) {
  return (
    <Button asChild variant="ghost" size="sm" className="text-muted-foreground">
      <Link to={to}>{children}</Link>
    </Button>
  );
}

function NeedsAttention({ items }: { items: Overview["needs_attention"] }) {
  return (
    <Card>
      <CardHeader title="Needs attention" actions={items.length ? <SectionLink to="/resources?view=attention">View in Resources</SectionLink> : null} />
      {items.length === 0 ? (
        <CardContent>
          <p className="py-2 text-sm text-muted-foreground">Everything monitored is healthy. Nothing needs your attention right now.</p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {items.map((r) => (
            <li key={r.id} className="grid grid-cols-12 items-center gap-x-4 gap-y-1 px-5 py-3 text-sm">
              <div className="col-span-12 flex min-w-0 items-center gap-2.5 md:col-span-4">
                <HealthDot status={r.health_status} />
                <Link to={`/resources/${r.id}`} className="truncate font-medium hover:underline">
                  {r.name}
                </Link>
              </div>
              <div className="col-span-6 truncate text-muted-foreground md:col-span-2">{r.type_display_name}</div>
              <div className="col-span-6 truncate text-muted-foreground md:col-span-2">
                {r.project_name ? `${r.project_name} / ${r.environment_name ?? "-"}` : "Unassigned"}
              </div>
              <div className={cn("col-span-12 md:col-span-4", r.health_status === "critical" ? "text-critical" : "text-warning")}>{r.reason}</div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Projects({ projects }: { projects: Overview["project_health"] }) {
  return (
    <Card>
      <CardHeader title="Projects" actions={<SectionLink to="/projects">Manage</SectionLink>} />
      {projects.length === 0 ? (
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No projects yet. <Link to="/projects" className="text-primary hover:underline">Create a project</Link> to group resources by
            application and environment.
          </p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {projects.map((p) => {
            const empty = p.counts.total === 0;
            return (
              <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
                <Link to={`/projects/${p.id}`} className={cn("w-44 shrink-0 truncate text-sm font-medium hover:underline", empty && "text-muted-foreground")}>
                  {p.name}
                </Link>
                {empty ? (
                  <span className="text-sm text-muted-foreground">No resources yet</span>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {p.environments
                      .filter((e) => e.counts.total > 0)
                      .map((e) => (
                        <Link
                          key={e.id}
                          to={`/projects/${p.id}?environment=${e.id}`}
                          className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1 text-xs hover:bg-muted/70"
                        >
                          <HealthDot status={e.status} className="size-2" />
                          {e.name}
                          <span className="tabular text-muted-foreground">{e.counts.total}</span>
                        </Link>
                      ))}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
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
  const query = useQuery({ queryKey: ["overview"], queryFn: endpoints.overview, refetchInterval: 60_000 });
  const connections = useQuery({ queryKey: ["connections"], queryFn: endpoints.connections });
  if (query.isLoading) return <LoadingBlock label="Loading overview" />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const o = query.data;

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

  const lastSync =
    (connections.data ?? [])
      .map((c) => c.last_sync_at)
      .filter((v): v is string => !!v)
      .sort()
      .pop() ?? null;

  return (
    <div className="space-y-6">
      <div>
        <Headline o={o} lastSync={lastSync} />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <KpiCard
            label="Monitored resources"
            value={o.totals.monitored_resources}
            hint={o.totals.inventory_resources ? `+${o.totals.inventory_resources.toLocaleString("en-GB")} inventory` : undefined}
          />
          <KpiCard label="Healthy" value={o.health.healthy} tone={o.health.healthy ? "healthy" : undefined} />
          <KpiCard label="Warning" value={o.health.warning} tone={o.health.warning ? "warning" : undefined} />
          <KpiCard label="Critical" value={o.health.critical} tone={o.health.critical ? "critical" : undefined} />
          <KpiCard label="Active alerts" value={o.alerts.active} tone={o.alerts.active ? "critical" : undefined} />
        </div>
      </div>

      {o.feed_errors.length > 0 ? (
        <div className="rounded-lg border border-warning/30 bg-warning/5 px-5 py-3 text-sm">
          {o.feed_errors.map((e) => (
            <p key={e.connection}>
              {e.connection}: {e.message}
            </p>
          ))}
        </div>
      ) : null}

      <NeedsAttention items={o.needs_attention} />
      <Projects projects={o.project_health} />
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <ActiveAlerts alerts={o.recent_alerts} total={o.alerts.active} />
        <ServiceHealth events={o.service_health} />
      </div>
      <RecentChanges changes={o.recent_changes} />
    </div>
  );
}
