import { useQuery } from "@tanstack/react-query";
import { endpoints } from "@/api/endpoints";
import { useFilters } from "@/stores/filters";
import { LIVE_REFRESH_MS, useLiveMode } from "@/stores/live";
import { timeRangeParams } from "@/utils/timeRange";

/**
 * All metric keys of one widget in one request; cached per resource + keys + time range.
 * While Live is on the range is the last hour and charts refresh every ``LIVE_REFRESH_MS``.
 */
export function useMetrics(resourceId: string | undefined, keys: string[]) {
  const { timeRange } = useFilters();
  const { live } = useLiveMode();
  const params = timeRangeParams(timeRange);
  const metrics = keys.join(",");
  return useQuery({
    queryKey: ["metrics", resourceId, metrics, params],
    queryFn: () => endpoints.metrics(resourceId as string, { metrics, ...params }),
    enabled: !!resourceId && keys.length > 0,
    staleTime: live ? 0 : 60_000,
    refetchInterval: live ? LIVE_REFRESH_MS : 120_000,
  });
}

export function useLogQuery(resourceId: string | undefined, queryKey: string | undefined) {
  const { timeRange } = useFilters();
  return useQuery({
    queryKey: ["log-widget", resourceId, queryKey, timeRange],
    queryFn: () =>
      endpoints.runLogQuery({
        resource_id: resourceId as string,
        query_key: queryKey,
        time_range: timeRange.preset,
        start: timeRange.preset === "custom" ? timeRange.start : undefined,
        end: timeRange.preset === "custom" ? timeRange.end : undefined,
      }),
    enabled: !!resourceId && !!queryKey,
    staleTime: 120_000,
    retry: false,
  });
}
