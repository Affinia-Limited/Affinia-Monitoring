import { cn } from "@/utils/cn";
import { TimeAgo } from "./status";

/**
 * Honest data freshness: when this page last fetched data, and when Azure data was last
 * synchronised or health last checked. Data is cached, never presented as real-time.
 */
export function Freshness({
  updatedAt,
  syncedAt,
  checkedAt,
  className,
}: {
  /** Milliseconds since epoch (React Query ``dataUpdatedAt``). */
  updatedAt?: number;
  syncedAt?: string | null;
  checkedAt?: string | null;
  className?: string;
}) {
  const parts = [];
  if (updatedAt) {
    parts.push(
      <span key="updated">
        Last updated <TimeAgo value={new Date(updatedAt).toISOString()} />
      </span>,
    );
  }
  if (checkedAt !== undefined) {
    parts.push(<span key="checked">Health checked {checkedAt ? <TimeAgo value={checkedAt} /> : "not yet"}</span>);
  }
  if (syncedAt !== undefined) {
    parts.push(<span key="synced">Azure data synchronised {syncedAt ? <TimeAgo value={syncedAt} /> : "not yet"}</span>);
  }
  if (!parts.length) return null;
  return (
    <p className={cn("flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground", className)}>
      {parts.map((p, i) => (
        <span key={i} className="inline-flex items-center gap-3">
          {i > 0 ? <span aria-hidden="true">·</span> : null}
          {p}
        </span>
      ))}
    </p>
  );
}
