import { Radio, WifiOff } from "lucide-react";
import { useLiveStale } from "@/hooks/useLiveResources";
import { LIVE_REFRESH_MS, useLiveMode } from "@/stores/live";
import type { HealthStatus, LiveMetric, LiveResourceState } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatValue } from "@/utils/format";
import { Sparkline } from "./Sparkline";
import { Button } from "./ui/button";
import { Tooltip } from "./ui/menu";

const RANK: Record<HealthStatus, number> = { critical: 3, warning: 2, healthy: 1, unknown: 0 };
const TEXT: Partial<Record<HealthStatus, string>> = { warning: "text-warning", critical: "text-critical" };
const OPERATOR: Record<string, string> = { gt: "above", gte: "at or above", lt: "below", lte: "at or below" };
const REDUCER: Record<string, string> = { avg: "average", sum: "total", max: "maximum", min: "minimum" };

/** Pulsing dot; static when motion is reduced. */
function Pulse({ className }: { className?: string }) {
  return (
    <span className={cn("relative flex size-2 shrink-0", className)} aria-hidden="true">
      <span className="absolute inline-flex size-full rounded-full bg-healthy opacity-60 motion-safe:animate-ping" />
      <span className="relative inline-flex size-2 rounded-full bg-healthy" />
    </span>
  );
}

/** Top-bar switch for Live mode across the whole dashboard. */
export function LiveToggle() {
  const { live, setLive } = useLiveMode();
  const stale = useLiveStale();
  return (
    <Tooltip
      content={
        stale
          ? "Live data unavailable, retrying. Values on screen are from the last successful update. Click to stop Live."
          : live
          ? `Live: per-resource status and the last hour of metrics, refreshed every ${LIVE_REFRESH_MS / 1000} seconds. Click to stop.`
          : `Show live status and metrics for every resource, refreshed every ${LIVE_REFRESH_MS / 1000} seconds`
      }
    >
      <Button
        variant="outline"
        size="sm"
        aria-pressed={live}
        aria-describedby={stale ? "live-stale-note" : undefined}
        onClick={() => setLive(!live)}
        className={cn(
          live && !stale && "border-healthy/40 bg-healthy/10 text-healthy hover:bg-healthy/15",
          stale && "border-warning/40 bg-warning/10 text-warning hover:bg-warning/15",
        )}
      >
        {stale ? <WifiOff /> : live ? <Pulse /> : <Radio />}
        Live
        {stale ? (
          <span id="live-stale-note" className="sr-only">
            Live data unavailable, retrying
          </span>
        ) : null}
      </Button>
    </Tooltip>
  );
}

/** Stands in for the time-range picker while Live is on: the window is fixed. */
export function LiveWindowLabel() {
  return (
    <span className="hidden h-8 items-center rounded-md border border-border px-2.5 text-xs text-muted-foreground sm:inline-flex">
      Last 60 minutes · every {LIVE_REFRESH_MS / 1000} s
    </span>
  );
}

/** Small "Live" marker next to a value that comes from live data; says so when updates have stopped. */
export function LiveMark({ className }: { className?: string }) {
  const stale = useLiveStale();
  if (stale) {
    return (
      <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground", className)} title="The last live update failed or is out of date. Retrying.">
        <WifiOff className="size-3" aria-hidden="true" />
        Live paused · retrying
      </span>
    );
  }
  return (
    <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium text-healthy", className)}>
      <Pulse className="size-1.5 [&>span]:size-1.5" />
      Live
    </span>
  );
}

/** While Live is on, says that the totals next to it come from the last scheduled health check. */
export function AsOfLastCheck({ className }: { className?: string }) {
  const { live } = useLiveMode();
  if (!live) return null;
  return <p className={cn("text-xs text-muted-foreground", className)}>Totals as of the last health check. Resource rows show live status.</p>;
}

/** The single most useful live metric: the worst-status one, otherwise the first with data. */
export function liveKeyMetric(state: LiveResourceState | undefined): LiveMetric | null {
  const metrics = (state?.metrics ?? []).filter((m) => m.latest !== null);
  if (!metrics.length) return null;
  return metrics.reduce((best, m) => (RANK[m.status] > RANK[best.status] ? m : best), metrics[0]);
}

/** Metrics ordered worst first, keeping the monitor's order within a status. */
export function liveMetricsByAttention(state: LiveResourceState | undefined): LiveMetric[] {
  return [...(state?.metrics ?? [])].sort((a, b) => RANK[b.status] - RANK[a.status]);
}

export function liveMetricTooltip(m: LiveMetric): string {
  if (m.unavailable_reason) return `${m.label}: no data (${m.unavailable_reason.replace(/_/g, " ").toLowerCase()})`;
  const window = `${m.window_minutes}-minute ${REDUCER[m.reducer] ?? m.reducer} ${formatValue(m.window_value, m.unit)}`;
  const thresholds = [
    m.warning !== null ? `warning ${OPERATOR[m.operator]} ${formatValue(m.warning, m.unit)}` : null,
    m.critical !== null ? `critical ${OPERATOR[m.operator]} ${formatValue(m.critical, m.unit)}` : null,
  ].filter(Boolean);
  return `${m.label}: latest ${formatValue(m.latest, m.unit)}, ${window}${thresholds.length ? ` (${thresholds.join(", ")})` : ""}`;
}

function trendLabel(m: LiveMetric): string {
  return `${m.label}, last ${m.values.length} minutes, latest ${formatValue(m.latest, m.unit)}`;
}

/** Compact "label value ~sparkline~" for table cells. Healthy lines stay neutral so problems stand out. */
export function LiveMetricInline({ metric, showLabel = true }: { metric: LiveMetric; showLabel?: boolean }) {
  return (
    <Tooltip content={liveMetricTooltip(metric)}>
      <span tabIndex={0} className="inline-flex items-center gap-2 whitespace-nowrap rounded outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {showLabel ? <span className="text-muted-foreground">{metric.label}</span> : null}
        <span className={cn("tabular font-medium", TEXT[metric.status])}>{formatValue(metric.latest, metric.unit)}</span>
        <Sparkline values={metric.values} label={trendLabel(metric)} width={64} height={18} className={TEXT[metric.status] ?? "text-info"} />
      </span>
    </Tooltip>
  );
}

/** Card for one live metric on the resource page. */
export function LiveMetricTile({ metric }: { metric: LiveMetric }) {
  return (
    <Tooltip content={liveMetricTooltip(metric)}>
      <div tabIndex={0} className="rounded-lg border border-border bg-card px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <p className="truncate text-xs text-muted-foreground" title={metric.label}>
          {metric.label}
        </p>
        <div className="mt-1 flex items-end justify-between gap-2">
          <p className={cn("tabular text-xl font-semibold", TEXT[metric.status])}>{formatValue(metric.latest, metric.unit)}</p>
          <Sparkline values={metric.values} label={trendLabel(metric)} width={72} height={28} className={TEXT[metric.status] ?? "text-info"} />
        </div>
        {metric.status === "warning" || metric.status === "critical" ? (
          <p className={cn("text-xs capitalize", TEXT[metric.status])}>{metric.status}</p>
        ) : metric.unavailable_reason ? (
          <p className="text-xs text-muted-foreground">No data</p>
        ) : null}
      </div>
    </Tooltip>
  );
}
