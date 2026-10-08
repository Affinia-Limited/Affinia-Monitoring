import { type ComponentType, lazy } from "react";

const RELOAD_KEY = "amp.chunk-reload";

/**
 * A page loaded on first visit. After a deployment the previous build's chunks no longer exist, so
 * a tab opened before the release fails to load them; reload once to fetch the new build instead of
 * showing a broken page. The flag stops a reload loop when the failure is something else.
 */
export function lazyPage<M extends Record<string, unknown>, K extends keyof M & string>(load: () => Promise<M>, name: K) {
  return lazy(async () => {
    try {
      const module = await load();
      sessionStorageSafe("remove");
      return { default: module[name] as ComponentType };
    } catch (error) {
      if (sessionStorageSafe("get") !== "1") {
        sessionStorageSafe("set");
        window.location.reload();
        return { default: () => null };
      }
      throw error;
    }
  });
}

function sessionStorageSafe(action: "get" | "set" | "remove"): string | null {
  try {
    if (action === "get") return window.sessionStorage.getItem(RELOAD_KEY);
    if (action === "set") window.sessionStorage.setItem(RELOAD_KEY, "1");
    else window.sessionStorage.removeItem(RELOAD_KEY);
  } catch {
    // Storage blocked: the error boundary handles the failure.
  }
  return null;
}
