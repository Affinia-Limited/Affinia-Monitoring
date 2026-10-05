import type { HealthCounts, HealthStatus } from "@/types/api";
import { cn } from "@/utils/cn";
import { HealthDot } from "./status";

export const HEALTH_LABELS: Record<HealthStatus, string> = {
  healthy: "Healthy",
  warning: "Warning",
  critical: "Critical",
  unknown: "Not checked",
};

const TEXT_TONE: Record<HealthStatus, string> = {
  healthy: "text-healthy",
  warning: "text-warning",
  critical: "text-critical",
  unknown: "text-muted-foreground",
};

function normalise(status: string | null | undefined): HealthStatus {
  return status === "healthy" || status === "warning" || status === "critical" ? status : "unknown";
}

/** "● Healthy": a dot plus the word, so status never relies on colour alone. */
export function HealthText({ status, className }: { status: string | null | undefined; className?: string }) {
  const s = normalise(status);
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-sm", className)}>
      <HealthDot status={s} label="" className="size-2" />
      <span className={cn("font-medium", s === "unknown" ? "text-muted-foreground" : "text-foreground")}>{HEALTH_LABELS[s]}</span>
    </span>
  );
}

/**
 * Share of *checked* resources that are healthy. Resources that have not been evaluated are excluded,
 * and the counts are always shown next to the score so it never needs to be guessed.
 */
export function healthScore(counts: HealthCounts): number | null {
  const checked = counts.healthy + counts.warning + counts.critical;
  return checked ? Math.round((counts.healthy / checked) * 100) : null;
}

const SEGMENTS: { key: keyof HealthCounts & HealthStatus; className: string }[] = [
  { key: "healthy", className: "bg-healthy" },
  { key: "warning", className: "bg-warning" },
  { key: "critical", className: "bg-critical" },
  { key: "unknown", className: "bg-unknown/50" },
];

/** Score, a proportional bar and the actual counts behind it. */
export function HealthSummary({ counts, title = "Health", className }: { counts: HealthCounts; title?: string; className?: string }) {
  const score = healthScore(counts);
  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-muted-foreground">{title}</p>
        <p className="tabular text-2xl font-semibold" aria-label={score === null ? "No health score yet" : `${score}% healthy`}>
          {score === null ? "-" : `${score}%`}
          {score !== null ? <span className="ml-1 text-sm font-normal text-muted-foreground">healthy</span> : null}
        </p>
      </div>
      {counts.total ? (
        <div className="flex h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          {SEGMENTS.map((s) =>
            counts[s.key] ? <div key={s.key} className={s.className} style={{ width: `${(counts[s.key] / counts.total) * 100}%` }} /> : null,
          )}
        </div>
      ) : null}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-4">
        {SEGMENTS.map((s) => (
          <div key={s.key} className="flex items-center gap-2">
            <HealthDot status={s.key} label="" className="size-2" />
            <dt className="text-muted-foreground">{HEALTH_LABELS[s.key]}</dt>
            <dd className={cn("tabular ml-auto font-medium sm:ml-0", counts[s.key] && s.key !== "healthy" ? TEXT_TONE[s.key] : "")}>
              {counts[s.key]}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
