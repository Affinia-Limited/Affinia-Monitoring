import { keepPreviousData, type Query, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";
import { endpoints } from "@/api/endpoints";
import { LIVE_REFRESH_MS, useLiveMode } from "@/stores/live";
import type { LiveResourceState } from "@/types/api";

/** The API's per-request limit (one page of the largest resource table). */
const MAX_IDS = 50;
const QUERY_KEY = "live-resources";
/** Readings older than this are no longer live (three missed polls). */
export const LIVE_STALE_AFTER_MS = 3 * LIVE_REFRESH_MS;

/** The last poll failed, or the newest reading is too old to call live. */
export function isLiveStale(state: { status: string; dataUpdatedAt: number }, now = Date.now()): boolean {
  return state.status === "error" || (state.dataUpdatedAt > 0 && now - state.dataUpdatedAt > LIVE_STALE_AFTER_MS);
}

export interface LiveResourcesResult {
  live: boolean;
  /** Last readings per resource id. Empty when Live is off, so callers fall back to the last health evaluation. */
  byId: Record<string, LiveResourceState>;
  /** The last poll failed (``byId`` may still hold older readings). */
  isError: boolean;
  /** Live is on but the readings are not current: show them as paused, not live. */
  stale: boolean;
  dataUpdatedAt: number;
}

/** Live state for the resources a view is showing, refreshed every ``LIVE_REFRESH_MS`` while Live is on. */
export function useLiveResources(ids: string[]): LiveResourcesResult {
  const { live } = useLiveMode();
  const wanted = [...new Set(ids)].sort().slice(0, MAX_IDS);
  const query = useQuery({
    queryKey: [QUERY_KEY, wanted],
    queryFn: () => endpoints.liveResources(wanted),
    enabled: live && wanted.length > 0,
    refetchInterval: LIVE_REFRESH_MS,
    staleTime: 0,
    // Keep the last readings on screen while the next set of rows loads.
    placeholderData: keepPreviousData,
  });
  return {
    live,
    byId: live ? (query.data?.resources ?? {}) : {},
    isError: live && query.isError,
    stale: live && isLiveStale(query),
    dataUpdatedAt: query.dataUpdatedAt,
  };
}

function anyStale(queries: Query[]): boolean {
  const now = Date.now();
  return queries.some((q) => q.getObserversCount() > 0 && isLiveStale(q.state, now));
}

/**
 * Whether any live view on screen is failing or out of date (for the top-bar Live switch and the
 * Live marks). Re-renders only when that answer changes.
 */
export function useLiveStale(): boolean {
  const qc = useQueryClient();
  const { live } = useLiveMode();
  const cache = qc.getQueryCache();
  const subscribe = useCallback((onChange: () => void) => cache.subscribe(onChange), [cache]);
  const snapshot = () => anyStale(cache.findAll({ queryKey: [QUERY_KEY] }));
  const stale = useSyncExternalStore(subscribe, snapshot, snapshot);
  return live && stale;
}
