import { useQuery } from "@tanstack/react-query";
import { Pause, Play, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { KpiCard, PageHeader } from "@/components/common";
import { Sparkline } from "@/components/Sparkline";
import { HealthDot, SeverityBadge, TimeAgo } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Tooltip } from "@/components/ui/menu";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useFilters } from "@/stores/filters";
import type { HealthStatus, Live, LiveEnvironment, LiveMetric, LiveResource } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatValue } from "@/utils/format";
import { paths } from "@/utils/paths";
import { diffLive, type LiveChange } from "./liveChanges";

/** How often the page polls while live. Azure Monitor metrics are per minute, so faster adds nothing. */
export const LIVE_REFRESH_MS = 15_000;
const MAX_CHANGES = 50;

const clock = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

const TEXT: Record<HealthStatus, string> = {
  healthy: "text-healthy",
  warning: "text-warning",
  critical: "text-critical",
  unknown: "text-muted-foreground",
};

const OPERATOR: Record<string, string> = { gt: "above", gte: "at or above", lt: "below", lte: "at or below" };
const REDUCER: Record<string, string> = { avg: "average", sum: "total", max: "maximum", min: "minimum" };

function LiveIndicator({ paused }: { paused: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
        paused ? "border-border text-muted-foreground" : "border-healthy/30 bg-healthy/10 text-healthy",
      )}
    >
      <span className="relative flex size-2">
        {!paused ? <span className="absolute inline-flex size-full rounded-full bg-healthy opacity-60 motion-safe:animate-ping" /> : null}
        <span className={cn("relative inline-flex size-2 rounded-full", paused ? "bg-unknown" : "bg-healthy")} />
      </span>
      {paused ? "Paused" : "Live"}
    </span>
  );
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
}

function EnvironmentTile({ env, changed }: { env: LiveEnvironment; changed: boolean }) {
  const bad = env.counts.critical + env.counts.warning;
  return (
    <Link
      to={paths.environment(env.project_id, env.environment_id)}
      className={cn(
        "block rounded-lg border border-border bg-card p-4 transition-shadow hover:bg-muted/40",
        changed && "ring-2 ring-info/50",
        env.status === "critical" && "border-critical/40",
        env.status === "warning" && "border-warning/40",
      )}
    >
      <div className="flex items-center gap-2">
        <HealthDot status={env.status} />
        <span className="truncate text-sm font-medium">{env.environment_name}</span>
        {env.active_alerts ? (
          <span className="tabular ml-auto rounded-full bg-critical/10 px-1.5 text-xs font-semibold text-critical" aria-label={`${env.active_alerts} open alerts`}>
            {env.active_alerts}
          </span>
        ) : null}
      </div>
      <p className="mt-0.5 truncate text-xs text-muted-foreground">{env.project_name}</p>
      <p className="mt-2 text-xs text-muted-foreground">
        {env.counts.total === 0
          ? "No monitored resources"
          : bad
            ? <span className={TEXT[env.status]}>{bad} of {plural(env.counts.total, "resource")} need attention</span>
            : `${plural(env.counts.total, "resource")}, all healthy`}
      </p>
    </Link>
  );
}

function metricTooltip(m: LiveMetric): string {
  if (m.unavailable_reason) return `${m.label}: no data (${m.unavailable_reason.replace(/_/g, " ").toLowerCase()})`;
  const window = `${m.window_minutes}-minute ${REDUCER[m.reducer] ?? m.reducer} ${formatValue(m.window_value, m.unit)}`;
  const thresholds = [
    m.warning !== null ? `warning ${OPERATOR[m.operator]} ${formatValue(m.warning, m.unit)}` : null,
    m.critical !== null ? `critical ${OPERATOR[m.operator]} ${formatValue(m.critical, m.unit)}` : null,
  ].filter(Boolean);
  return `${m.label}: ${window}${thresholds.length ? ` (${thresholds.join(", ")})` : ""}`;
}

function MetricCell({ metric }: { metric: LiveMetric }) {
  // Healthy lines stay neutral so warnings and criticals stand out.
  const tone = metric.status === "warning" || metric.status === "critical" ? TEXT[metric.status] : "text-info";
  return (
    <Tooltip content={metricTooltip(metric)}>
      <div tabIndex={0} className="flex min-w-0 items-center gap-3 rounded-md px-1 py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs text-muted-foreground">{metric.label}</p>
          <p className={cn("tabular text-sm font-semibold", metric.status === "healthy" || metric.status === "unknown" ? "" : TEXT[metric.status])}>
            {formatValue(metric.latest, metric.unit)}
          </p>
        </div>
        <Sparkline
          className={tone}
          values={metric.points.map((p) => p.value)}
          label={`${metric.label}, last ${metric.points.length} minutes, latest ${formatValue(metric.latest, metric.unit)}`}
        />
      </div>
    </Tooltip>
  );
}

function ResourceRow({ resource }: { resource: LiveResource }) {
  return (
    <li className="grid grid-cols-1 gap-3 px-5 py-3 lg:grid-cols-[minmax(0,16rem)_1fr] lg:items-center">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <HealthDot status={resource.health_status} />
          <Link to={paths.resource(resource.id)} className="truncate text-sm font-medium hover:underline">
            {resource.name}
          </Link>
          {resource.active_alerts ? (
            <span className="tabular rounded-full bg-critical/10 px-1.5 text-xs font-semibold text-critical" aria-label={`${resource.active_alerts} open alerts`}>
              {resource.active_alerts}
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {resource.type_display_name} · {resource.project_name ? `${resource.project_name} / ${resource.environment_name ?? "-"}` : "Unassigned"}
        </p>
      </div>
      {resource.metrics.length ? (
        <div className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 xl:grid-cols-3">
          {resource.metrics.map((m) => (
            <MetricCell key={m.key} metric={m} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No live metrics for this resource type.</p>
      )}
    </li>
  );
}

function ChangeFeed({ changes, since }: { changes: LiveChange[]; since: number }) {
  return (
    <Card>
      <CardHeader title="Changes" description={`Seen by this page since ${clock.format(since)}`} />
      {changes.length === 0 ? (
        <CardContent>
          <p className="text-sm text-muted-foreground">No status changes or new alerts yet. Changes appear here as they happen.</p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70" aria-live="polite">
          {changes.map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-5 py-3 text-sm">
              <HealthDot status={c.tone} label="" />
              <div className="min-w-0 flex-1">
                <Link to={c.href} className="block truncate font-medium hover:underline">
                  {c.title}
                </Link>
                <p className="truncate text-xs text-muted-foreground">{c.detail}</p>
              </div>
              <span className="tabular shrink-0 text-xs text-muted-foreground">{clock.format(new Date(c.at))}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function OpenAlerts({ live }: { live: Live }) {
  return (
    <Card>
      <CardHeader title="Open alerts" actions={<Button asChild variant="ghost" size="sm" className="text-muted-foreground"><Link to="/alerts">View all</Link></Button>} />
      {live.recent_alerts.length === 0 ? (
        <CardContent>
          <p className="text-sm text-muted-foreground">No open alerts.</p>
        </CardContent>
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {live.recent_alerts.map((a) => (
            <li key={a.id} className="flex items-center gap-3 px-5 py-3 text-sm">
              <SeverityBadge severity={a.severity} />
              <div className="min-w-0 flex-1">
                <Link to={paths.resource(a.resource_id)} className="block truncate font-medium hover:underline" title={a.title}>
                  {a.title}
                </Link>
                <p className="truncate text-xs text-muted-foreground">{[a.project_name, a.environment_name].filter(Boolean).join(" / ") || "Unassigned"}</p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">
                <TimeAgo value={a.started_at} />
              </span>
            </li>
          ))}
          {live.alerts.active > live.recent_alerts.length ? (
            <li className="px-5 py-2 text-xs text-muted-foreground">and {live.alerts.active - live.recent_alerts.length} more</li>
          ) : null}
        </ul>
      )}
    </Card>
  );
}

/** Polls the Live endpoint and keeps a feed of what changed between polls. */
function useLive(projectId: string | null, environmentId: string | null, paused: boolean) {
  const scope = `${projectId ?? ""}/${environmentId ?? ""}`;
  const query = useQuery({
    queryKey: ["live", { projectId, environmentId }],
    queryFn: () => endpoints.live({ project_id: projectId, environment_id: environmentId }),
    // Stops automatically while the browser tab is hidden (refetchIntervalInBackground is off).
    refetchInterval: paused ? false : LIVE_REFRESH_MS,
    staleTime: 0,
    retry: 1,
  });
  const [feed, setFeed] = useState<{ scope: string; since: number; changes: LiveChange[]; changed: Set<string> }>(() => ({
    scope,
    since: Date.now(),
    changes: [],
    changed: new Set(),
  }));
  const previous = useRef<{ scope: string; data: Live } | null>(null);

  useEffect(() => {
    const data = query.data;
    if (!data) return;
    const prev = previous.current;
    previous.current = { scope, data };
    if (!prev || prev.scope !== scope) {
      setFeed({ scope, since: Date.now(), changes: [], changed: new Set() });
      return;
    }
    if (prev.data.generated_at === data.generated_at) return;
    const changes = diffLive(prev.data, data);
    const changed = new Set(changes.filter((c) => c.kind === "environment").map((c) => c.href));
    setFeed((f) => ({ ...f, changes: [...[...changes].reverse(), ...f.changes].slice(0, MAX_CHANGES), changed }));
  }, [query.data, scope]);

  return { query, feed: feed.scope === scope ? feed : { scope, since: Date.now(), changes: [], changed: new Set<string>() } };
}

export function LivePage() {
  const { projectId, environmentId } = useFilters();
  const [paused, setPaused] = useState(false);
  const { query, feed } = useLive(projectId, environmentId, paused);
  const live = query.data;

  const header = (
    <PageHeader
      title="Live"
      badge={<LiveIndicator paused={paused} />}
      description={`Current status across ${projectId ? "the selected scope" : "all projects and environments"}, with the last hour of metrics at 1-minute resolution. Updates every ${LIVE_REFRESH_MS / 1000} seconds.`}
      actions={
        <>
          {live ? (
            <span className="text-xs text-muted-foreground" aria-live="off">
              Updated <span className="tabular">{clock.format(query.dataUpdatedAt)}</span>
            </span>
          ) : null}
          <Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching} aria-label="Refresh now">
            <RefreshCw className={cn(query.isFetching && "motion-safe:animate-spin")} />
          </Button>
          <Button variant={paused ? "default" : "outline"} size="sm" onClick={() => setPaused((p) => !p)}>
            {paused ? <Play /> : <Pause />}
            {paused ? "Resume" : "Pause"}
          </Button>
        </>
      }
    />
  );

  if (query.isLoading) {
    return (
      <div>
        {header}
        <LiveSkeleton />
      </div>
    );
  }
  if (!live) {
    return (
      <div>
        {header}
        <ErrorState error={query.error} title="Unable to load live data." onRetry={() => void query.refetch()} />
      </div>
    );
  }

  const h = live.health;
  return (
    <div className="space-y-6">
      {header}

      {query.isError ? (
        <div role="alert" className="rounded-lg border border-warning/30 bg-warning/5 px-5 py-3 text-sm">
          <p className="font-medium">The last update failed. Showing data from {clock.format(query.dataUpdatedAt)}.</p>
          <p className="text-muted-foreground">The page keeps retrying every {LIVE_REFRESH_MS / 1000} seconds.</p>
        </div>
      ) : null}

      <section aria-label="Live status summary" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard label="Healthy" value={h.healthy} tone={h.healthy ? "healthy" : undefined} hint={plural(h.total, "monitored resource")} />
        <KpiCard label="Warning" value={h.warning} tone={h.warning ? "warning" : undefined} hint="resources" />
        <KpiCard label="Critical" value={h.critical} tone={h.critical ? "critical" : undefined} hint="resources" />
        <KpiCard label="Not checked" value={h.unknown} hint="no health signal yet" />
        <KpiCard
          label="Open alerts"
          value={live.alerts.active}
          tone={live.alerts.active ? "critical" : undefined}
          hint={live.alerts.by_severity.critical ? `${live.alerts.by_severity.critical} critical` : "Nothing critical"}
        />
      </section>

      <section aria-labelledby="live-environments">
        <h2 id="live-environments" className="mb-3 text-base font-semibold">
          Environments
        </h2>
        {live.environments.length === 0 ? (
          <Card>
            <EmptyState title="No environments in scope" description="Add a project with environments to see their live status here." />
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {live.environments.map((e) => (
              <EnvironmentTile key={e.environment_id} env={e} changed={feed.changed.has(paths.environment(e.project_id, e.environment_id))} />
            ))}
          </div>
        )}
      </section>

      <Card>
        <CardHeader
          title="Live metrics"
          description={
            live.resources.length < live.resources_total
              ? `Worst ${live.resources.length} of ${live.resources_total} monitored resources. Choose a project or environment to see others.`
              : "Key health metrics per resource, last 60 minutes. Hover a metric for its health window and thresholds."
          }
        />
        {live.resources.length === 0 ? (
          <CardContent>
            <p className="text-sm text-muted-foreground">No monitored resources in this scope.</p>
          </CardContent>
        ) : (
          <ul className="divide-y divide-border/70 border-t border-border/70">
            {live.resources.map((r) => (
              <ResourceRow key={r.id} resource={r} />
            ))}
          </ul>
        )}
        <p className="border-t border-border/70 px-5 py-2 text-xs text-muted-foreground">
          Azure Monitor publishes metrics with a delay of a minute or two. Resource health status is evaluated every few minutes; open a resource to re-evaluate it now.
        </p>
      </Card>

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <OpenAlerts live={live} />
        <ChangeFeed changes={feed.changes} since={feed.since} />
      </div>
    </div>
  );
}

function LiveSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading live data">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}
