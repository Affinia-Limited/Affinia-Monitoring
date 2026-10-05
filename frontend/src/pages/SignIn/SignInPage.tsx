import { Activity, LogIn } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/**
 * Shown in Entra mode when the browser has no signed-in Microsoft account.
 * Sign-in is Microsoft Entra SSO only: the platform never handles passwords.
 */
export function SignInPage({ onSignIn, error }: { onSignIn: () => Promise<void> | void; error?: string | null }) {
  const [busy, setBusy] = useState(false);
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <Card className="w-full max-w-sm p-8 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Activity className="size-5" aria-hidden="true" />
        </div>
        <h1 className="mt-5 text-lg font-semibold tracking-tight">Azure Monitoring Platform</h1>
        <p className="mt-2 text-sm text-muted-foreground">Sign in with your organisation's Microsoft account to continue.</p>
        {error ? (
          <p role="alert" className="mt-4 rounded-md border border-critical/30 bg-critical/5 p-3 text-sm">
            {error}
          </p>
        ) : null}
        <Button
          className="mt-6 w-full"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onSignIn();
            } finally {
              setBusy(false);
            }
          }}
        >
          <LogIn />
          {busy ? "Redirecting to Microsoft..." : "Sign in with Microsoft"}
        </Button>
        <p className="mt-4 text-xs text-muted-foreground">Access is granted by your platform administrator.</p>
      </Card>
    </main>
  );
}
