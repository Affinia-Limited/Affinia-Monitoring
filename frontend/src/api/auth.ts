import {
  type AccountInfo,
  type Configuration,
  EventType,
  InteractionRequiredAuthError,
  PublicClientApplication,
} from "@azure/msal-browser";
import { env } from "@/utils/env";

let instance: PublicClientApplication | null = null;

export const SESSION_PENDING_KEY = "amp.session.pending";

/** MSAL instance, created only in Entra mode. Tokens are cached in sessionStorage, never localStorage. */
export function getMsal(): PublicClientApplication | null {
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

/** Returns an access token for the API, or starts an interactive redirect when required. */
export async function acquireApiToken(): Promise<string | null> {
  const msal = getMsal();
  if (!msal) return null;
  const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
  if (!account) {
    await msal.loginRedirect(loginRequest());
    return null;
  }
  try {
    const result = await msal.acquireTokenSilent({ ...loginRequest(), account });
    return result.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      await msal.acquireTokenRedirect({ ...loginRequest(), account });
      return null;
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
