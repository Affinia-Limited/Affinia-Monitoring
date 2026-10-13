import { LogIn } from "lucide-react";
import { useState } from "react";
import affiniaLogo from "@/assets/affinia-logo.png";
import { Button } from "@/components/ui/button";

/**
 * Shown in Entra mode when the browser has no signed-in Microsoft account.
 * Sign-in is Microsoft Entra SSO only: the platform never handles passwords.
 */
export function SignInPage({ onSignIn, error }: { onSignIn: () => Promise<void> | void; error?: string | null }) {
  const [busy, setBusy] = useState(false);
  return (
    <main className="grid min-h-screen bg-background lg:grid-cols-2">
      {/* Affinia brand panel: Forest Green with the wordmark in white. */}
      <section
        aria-label="Affinia Monitoring"
        className="flex flex-col justify-between bg-[#002729] px-8 py-10 text-white sm:px-12 lg:py-14"
      >
        <img src={affiniaLogo} alt="Affinia" className="h-9 w-auto self-start brightness-0 invert" />
        <div className="mt-12 max-w-md lg:mt-0">
          <p className="text-xs font-semibold tracking-wider text-[#D5F2E3] uppercase">Monitoring</p>
          <h2 className="mt-3 text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
            Every project, environment and resource, in one place.
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-[#D5F2E3]">
            Live health, alerts and logs for your Azure estate, with access matched to your role.
          </p>
        </div>
        <span aria-hidden="true" className="mt-12 hidden h-1 w-16 rounded-full bg-[#FF6633] lg:block" />
      </section>

      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
          <p className="mt-2 text-sm text-muted-foreground">Use your organisation&apos;s Microsoft account to continue.</p>
          {error ? (
            <p role="alert" className="mt-5 rounded-md border border-critical/30 bg-critical/5 p-3 text-sm">
              {error}
            </p>
          ) : null}
          <Button
            className="mt-6 h-10 w-full"
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
        </div>
      </section>
    </main>
  );
}
