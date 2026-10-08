import type { HealthStatus, Live } from "@/types/api";
import { paths } from "@/utils/paths";

export interface LiveChange {
  id: string;
  at: string;
  kind: "environment" | "resource" | "alert";
  /** Where to go for detail. */
  href: string;
  title: string;
  detail: string;
  /** Drives the dot colour: the new status, or the alert severity. */
  tone: HealthStatus;
}

/** Matches the API's ``recent_alerts`` limit. */
export const RECENT_ALERTS_LIMIT = 8;

const RANK: Record<HealthStatus, number> = { unknown: 0, healthy: 1, warning: 2, critical: 3 };

function movement(from: HealthStatus, to: HealthStatus): string {
  if (to === "healthy") return `recovered from ${from}`;
  if (RANK[to] > RANK[from]) return `${from === "unknown" ? "now" : "worsened to"} ${to}`;
  return `improved to ${to}`;
}

/**
 * What changed between two consecutive Live responses: environment and resource status
 * transitions and newly opened alerts. Resources that only entered or left the
 * worst-first list are not changes.
 */
export function diffLive(prev: Live, next: Live): LiveChange[] {
  const at = next.generated_at;
  const changes: LiveChange[] = [];

  const envBefore = new Map(prev.environments.map((e) => [e.environment_id, e.status]));
  for (const e of next.environments) {
    const before = envBefore.get(e.environment_id);
    if (before && before !== e.status) {
      changes.push({
        id: `env-${e.environment_id}-${at}`,
        at,
        kind: "environment",
        href: paths.environment(e.project_id, e.environment_id),
        title: `${e.project_name} / ${e.environment_name}`,
        detail: `Environment ${movement(before, e.status)}`,
        tone: e.status,
      });
    }
  }

  const resBefore = new Map(prev.resources.map((r) => [r.id, r.health_status]));
  for (const r of next.resources) {
    const before = resBefore.get(r.id);
    if (before && before !== r.health_status) {
      changes.push({
        id: `res-${r.id}-${at}`,
        at,
        kind: "resource",
        href: paths.resource(r.id),
        title: r.name,
        detail: `${r.type_display_name} ${movement(before, r.health_status)}`,
        tone: r.health_status,
      });
    }
  }

  const known = new Set(prev.recent_alerts.map((a) => a.id));
  // ``recent_alerts`` is the newest few. When the previous list was full, an unseen alert older
  // than all of it was simply outside the list (e.g. after one was resolved), not newly opened.
  const full = prev.recent_alerts.length >= RECENT_ALERTS_LIMIT;
  const oldest = Math.min(...prev.recent_alerts.map((a) => Date.parse(a.started_at)));
  for (const a of next.recent_alerts) {
    if (known.has(a.id) || (full && Date.parse(a.started_at) < oldest)) continue;
    changes.push({
      id: `alert-${a.id}`,
      at: a.started_at,
      kind: "alert",
      href: paths.resource(a.resource_id),
      title: a.title,
      detail: [a.resource_name, [a.project_name, a.environment_name].filter(Boolean).join(" / ")].filter(Boolean).join(" · ") || "New alert",
      tone: a.severity === "info" ? "unknown" : a.severity,
    });
  }
  return changes;
}
