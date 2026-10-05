import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";
import { errorMessage } from "@/api/client";
import { cn } from "@/utils/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden="true" />;
}

export function LoadingBlock({ label = "Loading", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} role="status" aria-label={label}>
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 px-6 py-10 text-center", className)}>
      <div className="text-muted-foreground">{icon ?? <Inbox className="size-8" />}</div>
      <p className="text-sm font-medium">{title}</p>
      {description ? <p className="max-w-md text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** Displays a structured API error: the safe message plus the request id for support. */
export function ErrorState({ error, className, compact }: { error: unknown; className?: string; compact?: boolean }) {
  const { message, requestId } = errorMessage(error);
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2 rounded-md border border-critical/30 bg-critical/5 text-sm",
        compact ? "p-2" : "p-3",
        className,
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-critical" />
      <div className="min-w-0">
        <p className="text-foreground">{message}</p>
        {requestId ? <p className="mt-0.5 text-xs text-muted-foreground">Request ID: {requestId}</p> : null}
      </div>
    </div>
  );
}
