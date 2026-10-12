import { useMe } from "@/hooks/useMe";
import type { AccessGrant } from "@/types/api";

/**
 * The signed-in user's data scope. ``unrestricted`` (Super Admin or "All projects") is required for
 * organisation-wide areas: Azure connections, notification settings, template defaults and the audit
 * log. UI hint only: the API enforces scope on every request.
 */
export function useAccess(): { loaded: boolean; unrestricted: boolean; grants: AccessGrant[] } {
  const { data } = useMe();
  return {
    loaded: !!data,
    // Before /auth/me loads (or from an older API), assume nothing extra is allowed.
    unrestricted: !!data?.access?.unrestricted,
    grants: data?.access?.grants ?? [],
  };
}
