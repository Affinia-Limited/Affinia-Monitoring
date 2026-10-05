/** Canonical URLs for the project hierarchy, so every link preserves context the same way. */
export const paths = {
  projects: () => "/projects",
  project: (projectId: string) => `/projects/${projectId}`,
  environment: (projectId: string, environmentId: string, tab?: string) =>
    `/projects/${projectId}/environments/${environmentId}${tab && tab !== "overview" ? `?tab=${tab}` : ""}`,
  resource: (resourceId: string) => `/resources/${resourceId}`,
  logs: (projectId?: string | null, environmentId?: string | null) => {
    const params = new URLSearchParams();
    if (projectId) params.set("project", projectId);
    if (environmentId) params.set("env", environmentId);
    const query = params.toString();
    return `/logs${query ? `?${query}` : ""}`;
  },
};

export function greeting(now: Date = new Date()): string {
  const hour = now.getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

/** "Aditya Kumar" -> "Aditya"; falls back to nothing for service-style names. */
export function firstName(displayName: string | null | undefined): string | null {
  const name = (displayName ?? "").trim();
  if (!name || name.includes("@") || name.includes("(")) return null;
  return name.split(/\s+/)[0] ?? null;
}
