import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
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

export function TableSkeleton({ rows = 6, label = "Loading", className }: { rows?: number; label?: string; className?: string }) {
  return (
    <div className={cn("space-y-3 p-4", className)} role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="size-2.5 rounded-full" />
          <Skeleton className="h-4 w-1/4" />
          <Skeleton className="h-4 w-1/6" />
          <Skeleton className="ml-auto h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

/**
 * Displays a structured API error: an optional plain-language title, the safe API message and the
 * request id for support. Raw server details are never shown (the API never returns them).
 */
export function ErrorState({
  error,
  className,
  compact,
  title,
  onRetry,
}: {
  error: unknown;
  className?: string;
  compact?: boolean;
  /** What could not be done, e.g. "Unable to load Production resources." */
  title?: string;
  onRetry?: () => void;
}) {
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
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium text-foreground">{title}</p> : null}
        <p className={title ? "mt-0.5 text-muted-foreground" : "text-foreground"}>{message}</p>
        {requestId ? <p className="mt-0.5 text-xs text-muted-foreground">Request ID: {requestId}</p> : null}
      </div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium hover:bg-muted"
        >
          <RefreshCw className="size-3.5" aria-hidden="true" />
          Retry
        </button>
      ) : null}
    </div>
  );
}
