import type { Widget } from "@/types/api";

export interface Thresholds {
  operator: "gt" | "gte" | "lt" | "lte";
  warning: number | null;
  critical: number | null;
}

export type ThresholdLevel = "healthy" | "warning" | "critical";

/** Reads `config.thresholds` added by the backend for metrics that have a health rule. */
export function widgetThresholds(widget: Widget): Thresholds | null {
  const raw = widget.config.thresholds as Partial<Thresholds> | undefined;
  if (!raw || typeof raw !== "object") return null;
  if (!raw.operator || !["gt", "gte", "lt", "lte"].includes(raw.operator)) return null;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const warning = num(raw.warning);
  const critical = num(raw.critical);
  if (warning === null && critical === null) return null;
  return { operator: raw.operator, warning, critical };
}

function breaches(value: number, operator: Thresholds["operator"], limit: number | null): boolean {
  if (limit === null) return false;
  switch (operator) {
    case "gt":
      return value > limit;
    case "gte":
      return value >= limit;
    case "lt":
      return value < limit;
    case "lte":
      return value <= limit;
  }
}

/** Same semantics as the backend health evaluator: critical first, then warning. */
export function thresholdLevel(value: number | null | undefined, thresholds: Thresholds | null): ThresholdLevel | null {
  if (!thresholds || value === null || value === undefined || !Number.isFinite(value)) return null;
  if (breaches(value, thresholds.operator, thresholds.critical)) return "critical";
  if (breaches(value, thresholds.operator, thresholds.warning)) return "warning";
  return "healthy";
}

/** CSS colour for a level; neutral primary when the metric has no thresholds. */
export function levelColour(level: ThresholdLevel | null): string {
  return level ? `var(--status-${level})` : "var(--primary)";
}
