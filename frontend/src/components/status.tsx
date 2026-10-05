import { AlertOctagon, AlertTriangle, CheckCircle2, HelpCircle, Info } from "lucide-react";
import type { AlertStatus, HealthStatus, Severity } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatDateTime, formatRelative } from "@/utils/format";
import { Badge } from "./ui/badge";
import { Tooltip } from "./ui/menu";

const HEALTH_LABEL: Record<HealthStatus, string> = {
  healthy: "Healthy",
  warning: "Warning",
  critical: "Critical",
  unknown: "Unknown",
};

const HEALTH_ICON = {
  healthy: CheckCircle2,
  warning: AlertTriangle,
  critical: AlertOctagon,
  unknown: HelpCircle,
} as const;

function normalise(status: string | null | undefined): HealthStatus {
  return status === "healthy" || status === "warning" || status === "critical" ? status : "unknown";
}

export function HealthBadge({ status, className }: { status: string | null | undefined; className?: string }) {
  const s = normalise(status);
  const Icon = HEALTH_ICON[s];
  return (
    <Badge tone={s} className={className} data-testid="health-badge">
      <Icon className="size-3" aria-hidden="true" />
      {HEALTH_LABEL[s]}
    </Badge>
  );
}

const DOT = {
  healthy: "bg-healthy",
  warning: "bg-warning",
  critical: "bg-critical",
  unknown: "bg-unknown",
} as const;

/** Pass ``label=""`` when the status is already spelled out next to the dot (decorative). */
export function HealthDot({ status, label, className }: { status: string | null | undefined; label?: string; className?: string }) {
  const s = normalise(status);
  if (label === "") return <span aria-hidden="true" className={cn("inline-block size-2.5 shrink-0 rounded-full", DOT[s], className)} />;
  return (
    <span
      role="img"
      aria-label={label ?? HEALTH_LABEL[s]}
      title={label ?? HEALTH_LABEL[s]}
      className={cn("inline-block size-2.5 shrink-0 rounded-full", DOT[s], className)}
    />
  );
}

export function SeverityBadge({ severity }: { severity: Severity | string }) {
  const tone = severity === "critical" ? "critical" : severity === "warning" ? "warning" : "info";
  const Icon = severity === "critical" ? AlertOctagon : severity === "warning" ? AlertTriangle : Info;
  return (
    <Badge tone={tone}>
      <Icon className="size-3" aria-hidden="true" />
      {severity.charAt(0).toUpperCase() + severity.slice(1)}
    </Badge>
  );
}

export function AlertStatusBadge({ status }: { status: AlertStatus | string }) {
  const tone = status === "active" ? "critical" : status === "acknowledged" ? "warning" : "healthy";
  return <Badge tone={tone}>{status.charAt(0).toUpperCase() + status.slice(1)}</Badge>;
}

/** Small, quiet top-bar pill, e.g. "Dev sign-in" or "Demo data". */
export function EnvironmentPill({ label, tooltip }: { label: string; tooltip: string }) {
  return (
    <Tooltip content={tooltip}>
      <span
        tabIndex={0}
        className="hidden shrink-0 items-center whitespace-nowrap rounded-full border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground sm:inline-flex"
      >
        {label}
      </span>
    </Tooltip>
  );
}

/** Relative time with the absolute DD/MM/YYYY HH:mm value on hover. */
export function TimeAgo({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-foreground">-</span>;
  return (
    <time dateTime={value} title={formatDateTime(value)}>
      {formatRelative(value)}
    </time>
  );
}
