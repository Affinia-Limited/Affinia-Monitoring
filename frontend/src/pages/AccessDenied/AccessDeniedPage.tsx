import { LockKeyhole, LogOut, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const MESSAGES = {
  ACCESS_NOT_GRANTED: {
    title: "Access not granted",
    body: "Your Microsoft account was authenticated successfully, but you have not been granted access to the Azure Monitoring Platform. Please contact your administrator to request access.",
  },
  ACCESS_SUSPENDED: {
    title: "Access suspended",
    body: "Your access to the Azure Monitoring Platform has been temporarily suspended. Please contact your administrator.",
  },
} as const;

export type AccessDeniedCode = keyof typeof MESSAGES;

/**
 * Shown when Entra ID authenticated the user but the API refused access. Deliberately
 * generic: it never reveals whether an account, invitation or role exists.
 */
export function AccessDeniedPage({
  code,
  account,
  onRetry,
  onSignOut,
}: {
  code: AccessDeniedCode;
  account: string | null;
  onRetry: () => void;
  onSignOut?: () => void;
}) {
  const message = MESSAGES[code] ?? MESSAGES.ACCESS_NOT_GRANTED;
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <Card className="w-full max-w-md p-8 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
          <LockKeyhole className="size-5 text-muted-foreground" aria-hidden="true" />
        </div>
        <h1 className="mt-5 text-lg font-semibold tracking-tight">{message.title}</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{message.body}</p>
        {account ? (
          <div className="mt-6 rounded-md border border-border bg-muted/50 px-4 py-3 text-sm">
            <div className="text-xs text-muted-foreground">Signed in as</div>
            <div className="mt-0.5 truncate font-medium">{account}</div>
          </div>
        ) : null}
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button variant="outline" onClick={onRetry}>
            <RefreshCw />
            Try again
          </Button>
          {onSignOut ? (
            <Button onClick={onSignOut}>
              <LogOut />
              Sign out
            </Button>
          ) : null}
        </div>
      </Card>
    </main>
  );
}
