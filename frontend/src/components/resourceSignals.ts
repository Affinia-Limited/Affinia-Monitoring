import type { HealthMetricReading, HealthReason, Resource } from "@/types/api";
import { formatValue } from "@/utils/format";

const RANK: Record<string, number> = { critical: 3, warning: 2, healthy: 1, unknown: 0 };

/**
 * The single most useful number for a resource: the worst-status reading, otherwise the first one
 * (monitor plugins list health rules most important first). Comes from the last health evaluation,
 * so no extra Azure calls are made.
 */
export function keyReading(resource: Pick<Resource, "health_metrics">): HealthMetricReading | null {
  const readings = resource.health_metrics ?? [];
  if (!readings.length) return null;
  return readings.reduce((best, r) => ((RANK[r.status] ?? 0) > (RANK[best.status] ?? 0) ? r : best), readings[0]);
}

export function formatReading(reading: HealthMetricReading): string {
  return formatValue(reading.value, reading.unit ?? "count");
}

/** The headline problem for a resource, e.g. "HTTP 5xx 42, above 10". */
export function topReason(reasons: HealthReason[]): HealthReason | null {
  if (!reasons.length) return null;
  return reasons.reduce((best, r) => ((RANK[r.severity] ?? 0) > (RANK[best.severity] ?? 0) ? r : best), reasons[0]);
}

const OPERATOR_WORD: Record<string, string> = { gt: "above", gte: "at or above", lt: "below", lte: "at or below" };

/** One line for issue lists: "HTTP 5xx 42, above the critical threshold of 10". */
export function shortReason(reason: HealthReason): string {
  if (reason.signal === "metric" && reason.value !== undefined) {
    const unit = reason.unit ?? "count";
    const word = OPERATOR_WORD[reason.operator ?? ""] ?? "past";
    return `${reason.label ?? reason.metric} ${formatValue(reason.value, unit)}, ${word} the ${reason.severity} threshold of ${formatValue(reason.threshold ?? null, unit)}`;
  }
  if (reason.signal === "resource_health") return `Azure Resource Health: ${reason.message}`;
  return reason.message;
}
