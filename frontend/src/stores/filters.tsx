import { createContext, type ReactNode, useCallback, useContext, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { isPreset, type TimeRangeValue } from "@/utils/timeRange";

interface FilterState {
  projectId: string | null;
  environmentId: string | null;
  timeRange: TimeRangeValue;
  setProject: (id: string | null) => void;
  setEnvironment: (id: string | null) => void;
  setTimeRange: (range: TimeRangeValue) => void;
}

const FilterContext = createContext<FilterState | null>(null);

/** Global filters (project, environment, time range) kept in the URL so views are shareable. */
export function FilterProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();

  const update = useCallback(
    (changes: Record<string, string | null | undefined>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(changes)) {
            if (v) next.set(k, v);
            else next.delete(k);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const value = useMemo<FilterState>(() => {
    const preset = params.get("range");
    return {
      projectId: params.get("project"),
      environmentId: params.get("env"),
      timeRange: {
        preset: isPreset(preset) ? preset : "24h",
        start: params.get("start") ?? undefined,
        end: params.get("end") ?? undefined,
      },
      setProject: (id) => update({ project: id, env: null }),
      setEnvironment: (id) => update({ env: id }),
      setTimeRange: (r) =>
        update({
          range: r.preset === "24h" ? null : r.preset,
          start: r.preset === "custom" ? r.start : null,
          end: r.preset === "custom" ? r.end : null,
        }),
    };
  }, [params, update]);

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
}

export function useFilters(): FilterState {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error("useFilters must be used inside FilterProvider");
  return ctx;
}
