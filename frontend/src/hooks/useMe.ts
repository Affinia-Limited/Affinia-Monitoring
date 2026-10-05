import { useQuery } from "@tanstack/react-query";
import { endpoints } from "@/api/endpoints";

export const PERMISSIONS = {
  viewDashboards: "dashboards:view",
  manageDashboards: "dashboards:manage",
  viewResources: "resources:view",
  viewLogs: "logs:view",
  runKql: "logs:run_kql",
  connectAzure: "azure:connect",
  syncAzure: "azure:sync",
  manageProjects: "projects:manage",
  viewAlerts: "alerts:view",
  manageAlerts: "alerts:manage",
  acknowledgeAlerts: "alerts:acknowledge",
  manageUsers: "users:manage",
  manageSettings: "settings:manage",
  viewAudit: "audit:view",
} as const;

export type PermissionKey = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: endpoints.me, staleTime: 5 * 60_000 });
}

/** UI-only permission check to hide controls. The API enforces every permission server-side. */
export function usePermission(permission: PermissionKey): boolean {
  const { data } = useMe();
  return !!data?.permissions.includes(permission);
}

export function useIsMock(): boolean {
  return useMe().data?.azure_provider === "mock";
}
