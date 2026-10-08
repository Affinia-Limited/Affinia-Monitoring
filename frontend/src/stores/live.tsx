import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";

/**
 * Polling period while Live is on. Azure Monitor metrics have 1-minute granularity and are cached per
 * minute on the server, so polls within a minute cost no Azure calls; they pick up status changes sooner.
 */
export const LIVE_REFRESH_MS = 5_000;
const STORAGE_KEY = "amp.live";

interface LiveState {
  live: boolean;
  setLive: (on: boolean) => void;
}

const LiveContext = createContext<LiveState | null>(null);

function load(): boolean {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Live mode: the whole dashboard shows per-resource live status and minute-by-minute metrics,
 * refreshing every few seconds (``LIVE_REFRESH_MS``). Remembered for this browser tab, so it survives navigation and reloads.
 */
export function LiveProvider({ children, initial }: { children: ReactNode; initial?: boolean }) {
  const [live, setLiveState] = useState(() => initial ?? load());
  const setLive = useCallback((on: boolean) => {
    setLiveState(on);
    try {
      window.sessionStorage.setItem(STORAGE_KEY, on ? "1" : "0");
    } catch {
      // A preference only.
    }
  }, []);
  const value = useMemo(() => ({ live, setLive }), [live, setLive]);
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLiveMode(): LiveState {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error("useLiveMode must be used inside LiveProvider");
  return ctx;
}

/** A query's refresh interval: ``normalMs`` normally, every ``LIVE_REFRESH_MS`` while Live is on. */
export function useRefreshInterval(normalMs: number | false): number | false {
  return useLiveMode().live ? LIVE_REFRESH_MS : normalMs;
}
