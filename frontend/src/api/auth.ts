import {
  type AccountInfo,
  BrowserAuthError,
  type Configuration,
  EventType,
  InteractionRequiredAuthError,
  PublicClientApplication,
} from "@azure/msal-browser";
import { env } from "@/utils/env";

let instance: PublicClientApplication | null = null;
let override: PublicClientApplication | null = null;

export const SESSION_PENDING_KEY = "amp.session.pending";

/** MSAL instance, created only in Entra mode. Tokens are cached in sessionStorage, never localStorage. */
export function getMsal(): PublicClientApplication | null {
  if (override) return override;
  if (env.authMode !== "entra") return null;
  if (!instance) {
    if (!env.clientId || !env.tenantId || !env.apiScope) {
      throw new Error("Entra authentication is enabled but the VITE_ENTRA_* settings are missing.");
    }
    const config: Configuration = {
      auth: {
        clientId: env.clientId,
        authority: `https://login.microsoftonline.com/${env.tenantId}`,
        redirectUri: env.redirectUri,
        postLogoutRedirectUri: env.redirectUri,
        navigateToLoginRequestUrl: true,
      },
      cache: { cacheLocation: "sessionStorage" },
    };
    instance = new PublicClientApplication(config);
    instance.addEventCallback((event) => {
      if (event.eventType === EventType.LOGIN_SUCCESS && event.payload && "account" in event.payload) {
        const account = (event.payload as { account: AccountInfo }).account;
        instance?.setActiveAccount(account);
        // Marker only (no token): tells the app to record the sign-in via POST /auth/session.
        sessionStorage.setItem(SESSION_PENDING_KEY, "1");
      }
    });
  }
  return instance;
}

export const loginRequest = () => ({ scopes: env.apiScope ? [env.apiScope] : [] });

/** Tests only: use a stand-in MSAL client (``null`` restores the real one). */
export function setMsalForTesting(msal: PublicClientApplication | null): void {
  override = msal;
  redirecting = null;
}

/**
 * Thrown instead of sending a request when the user must sign in again. The browser is already
 * being redirected to Microsoft, so callers should not treat it as a failure to report.
 */
export class ReauthenticationRequiredError extends Error {
  readonly code = "REAUTHENTICATING";
  constructor() {
    super("Your session has expired. Signing you in again...");
  }
}

let redirecting: Promise<void> | null = null;

/**
 * Starts one interactive sign-in, however many requests need it at once. MSAL allows a single
 * interaction at a time; parallel calls (e.g. polling while Live is on) would otherwise fail with
 * ``interaction_in_progress``.
 */
export function reauthenticate(): Promise<void> {
  const msal = getMsal();
  if (!msal) return Promise.resolve();
  if (!redirecting) {
    const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
    redirecting = (account ? msal.acquireTokenRedirect({ ...loginRequest(), account }) : msal.loginRedirect(loginRequest())).catch(
      (error: unknown) => {
        // Another tab or flow already owns the interaction: it will complete the sign-in.
        if (error instanceof BrowserAuthError && error.errorCode === "interaction_in_progress") return;
        redirecting = null;
        throw error;
      },
    );
  }
  return redirecting;
}

/**
 * Starts the shared sign-in without waiting for it: the redirect navigates away, so its promise may
 * never settle, and requests must fail fast instead of hanging.
 */
export function startReauthentication(): void {
  reauthenticate().catch((error: unknown) => console.error("reauthentication_failed", error));
}

/**
 * An access token for the API. When the user must interact (no account, expired session), starts a
 * single redirect and throws ``ReauthenticationRequiredError``, so no request is sent without a token.
 */
export async function acquireApiToken(): Promise<string | null> {
  const msal = getMsal();
  if (!msal) return null;
  if (redirecting) throw new ReauthenticationRequiredError();
  const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
  if (!account) {
    startReauthentication();
    throw new ReauthenticationRequiredError();
  }
  try {
    const result = await msal.acquireTokenSilent({ ...loginRequest(), account });
    return result.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      startReauthentication();
      throw new ReauthenticationRequiredError();
    }
    throw error;
  }
}

/** The Microsoft account the browser is signed in with (from MSAL, not from the API). */
export function signedInAccountName(): string | null {
  const msal = getMsal();
  const account = msal?.getActiveAccount() ?? msal?.getAllAccounts()[0];
  return account?.username ?? null;
}

/** Ends the Entra session. Callers clear cached application data first (see useSignOut). */
export async function signOut(): Promise<void> {
  sessionStorage.removeItem(SESSION_PENDING_KEY);
  const msal = getMsal();
  if (!msal) return;
  const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
  await msal.logoutRedirect(account ? { account } : undefined);
}
