import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { HEALTH_LABELS, HealthText } from "@/components/health";
import { TimeAgo } from "@/components/status";
import { Card } from "@/components/ui/card";
import type { EnvironmentSummary } from "@/types/api";
import { cn } from "@/utils/cn";
import { paths } from "@/utils/paths";

const COUNT_TONE = { healthy: "", warning: "text-warning", critical: "text-critical" } as const;

export function EnvironmentCard({ projectId, environment }: { projectId: string; environment: EnvironmentSummary }) {
  const e = environment;
  return (
    <Card className="flex h-full flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="truncate text-base font-semibold">
          <Link to={paths.environment(projectId, e.id)} className="hover:underline">
            {e.name}
          </Link>
        </h3>
        <HealthText status={e.health.total ? e.status : "unknown"} />
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        {e.health.total.toLocaleString("en-GB")} resource{e.health.total === 1 ? "" : "s"}
      </p>
      <dl className="mt-4 grid grid-cols-3 gap-2 text-sm">
        {(["healthy", "warning", "critical"] as const).map((k) => (
          <div key={k}>
            <dt className="text-xs text-muted-foreground">{HEALTH_LABELS[k]}</dt>
            <dd className={cn("tabular text-lg font-semibold", e.health[k] ? COUNT_TONE[k] : "")}>{e.health[k]}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
        <span className={e.active_alerts ? "font-medium text-critical" : ""}>
          {e.active_alerts} active alert{e.active_alerts === 1 ? "" : "s"}
        </span>
        <span>{e.last_checked_at ? <>Checked <TimeAgo value={e.last_checked_at} /></> : "Not checked yet"}</span>
      </div>
      <Link
        to={paths.environment(projectId, e.id)}
        className="mt-3 inline-flex items-center gap-1 self-end text-sm font-medium text-primary hover:underline"
        aria-label={`Open environment ${e.name}`}
      >
        Open environment <ArrowRight className="size-4" aria-hidden="true" />
      </Link>
    </Card>
  );
}
