import { useSearchParams } from "react-router-dom";

/** The global filters kept in the URL (see FilterProvider). */
const FILTER_KEYS = ["project", "env", "range", "start", "end"] as const;
/** Time only: for links whose path already fixes the project and environment. */
export const TIME_FILTER_KEYS = ["range", "start", "end"] as const;

/**
 * Appends the current global filters to an in-app link, so moving between pages keeps the chosen
 * project, environment and time range instead of silently resetting them.
 */
export function useWithFilters(keys: readonly string[] = FILTER_KEYS): (to: string) => string {
  const [params] = useSearchParams();
  const kept = keys.filter((k) => params.get(k)).map((k) => [k, params.get(k) as string] as const);
  return (to: string) => {
    if (!kept.length) return to;
    const [path, query = ""] = to.split("?");
    const next = new URLSearchParams(query);
    for (const [k, v] of kept) if (!next.has(k)) next.set(k, v);
    return `${path}?${next.toString()}`;
  };
}
