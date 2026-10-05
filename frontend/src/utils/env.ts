export type AuthMode = "entra" | "dev";

function read(name: string): string | undefined {
  const value = (import.meta.env as Record<string, string | undefined>)[name];
  return value && value.trim() ? value.trim() : undefined;
}

export const env = {
  authMode: (read("VITE_AUTH_MODE") === "entra" ? "entra" : "dev") as AuthMode,
  clientId: read("VITE_ENTRA_CLIENT_ID"),
  tenantId: read("VITE_ENTRA_TENANT_ID"),
  apiScope: read("VITE_ENTRA_API_SCOPE"),
  /** Same-origin by default; the nginx container proxies /api to the backend. */
  apiBaseUrl: read("VITE_API_BASE_URL") ?? "/api/v1",
  redirectUri: read("VITE_ENTRA_REDIRECT_URI") ?? (typeof window !== "undefined" ? window.location.origin : undefined),
};
