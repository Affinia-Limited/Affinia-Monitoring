import { MsalProvider } from "@azure/msal-react";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { getMsal, loginRequest, SESSION_PENDING_KEY, signedInAccountName } from "@/api/auth";
import { isAccessDenied, onAccessDenied } from "@/api/client";
import { endpoints } from "@/api/endpoints";
import { ErrorState } from "@/components/ui/states";
import { useMe } from "@/hooks/useMe";
import { useSignOut } from "@/hooks/useSignOut";
import { type AccessDeniedCode, AccessDeniedPage } from "@/pages/AccessDenied/AccessDeniedPage";
import { SignInPage } from "@/pages/SignIn/SignInPage";
import { env } from "@/utils/env";

function Splash({ message }: { message: string }) {
  return (
    <div className="flex h-screen items-center justify-center text-sm text-muted-foreground" role="status">
      {message}
    </div>
  );
}

/**
 * Renders the application only after the API has confirmed the caller is an active
 * member (GET /auth/me). Nothing protected is rendered or fetched before that.
 * If any later request reports that access was revoked, cached data is dropped and
 * the access page replaces the application immediately.
 */
export function MeGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useMe();
  const signOut = useSignOut();
  const [revoked, setRevoked] = useState<AccessDeniedCode | null>(null);

  useEffect(
    () =>
      onAccessDenied((error) => {
        setRevoked(error.code as AccessDeniedCode);
        // Drop everything except the failed identity check so no protected data stays in memory.
        qc.removeQueries({ predicate: (query) => query.queryKey[0] !== "me" });
      }),
    [qc],
  );

  const deniedCode = revoked ?? (isAccessDenied(me.error) ? (me.error.code as AccessDeniedCode) : null);
  if (deniedCode) {
    return (
      <AccessDeniedPage
        code={deniedCode}
        account={signedInAccountName()}
        onRetry={() => {
          setRevoked(null);
          void qc.resetQueries({ queryKey: ["me"] });
        }}
        onSignOut={env.authMode === "entra" ? () => void signOut() : undefined}
      />
    );
  }
  if (me.isLoading) return <Splash message="Checking access..." />;
  if (me.isError) {
    return (
      <div className="mx-auto mt-24 max-w-lg px-4">
        <ErrorState error={me.error} />
      </div>
    );
  }
  return <>{children}</>;
}

/** Entra mode: complete the redirect flow, show the sign-in page without an account, then audit the sign-in once. */
function EntraGate({ children }: { children: ReactNode }) {
  const msal = getMsal();
  const qc = useQueryClient();
  const [ready, setReady] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const [signInError, setSignInError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!msal) return;
    let cancelled = false;
    (async () => {
      try {
        await msal.initialize();
        let result = null;
        try {
          result = await msal.handleRedirectPromise();
        } catch {
          // Cancelled or failed at Microsoft: let the user retry from the sign-in page.
          if (!cancelled) setSignInError("Sign-in did not complete. Please try again.");
        }
        if (result?.account) msal.setActiveAccount(result.account);
        const account = msal.getActiveAccount() ?? msal.getAllAccounts()[0];
        if (!account) {
          if (!cancelled) setSignedOut(true);
          return;
        }
        msal.setActiveAccount(account);
        if (sessionStorage.getItem(SESSION_PENDING_KEY)) {
          sessionStorage.removeItem(SESSION_PENDING_KEY);
          try {
            qc.setQueryData(["me"], await endpoints.startSession());
          } catch (sessionError) {
            // Authenticated but not approved: MeGate shows the access page from GET /auth/me.
            if (!isAccessDenied(sessionError)) throw sessionError;
          }
        }
        if (!cancelled) setReady(true);
      } catch {
        if (!cancelled) setError("Sign-in could not be completed. Refresh the page to try again.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [msal, qc]);

  if (!msal) return null;
  if (error) return <Splash message={error} />;
  if (signedOut) return <SignInPage error={signInError} onSignIn={() => msal.loginRedirect(loginRequest())} />;
  return <MsalProvider instance={msal}>{ready ? <MeGate>{children}</MeGate> : <Splash message="Signing you in..." />}</MsalProvider>;
}

export function AuthGate({ children }: { children: ReactNode }) {
  if (env.authMode === "entra") return <EntraGate>{children}</EntraGate>;
  return <MeGate>{children}</MeGate>;
}
