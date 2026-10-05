import { CircleSlash } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { cn } from "@/utils/cn";

export function WidgetFrame({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <Card className={cn("flex h-full flex-col", className)} data-testid="widget">
      <CardHeader title={title} description={description} actions={actions} />
      <CardContent className={cn("min-h-0 flex-1", bodyClassName)}>{children}</CardContent>
    </Card>
  );
}

export function WidgetLoading({ height = 180 }: { height?: number }) {
  return (
    <div role="status" aria-label="Loading">
      <Skeleton className="w-full" />
      <div className="skeleton w-full" style={{ height }} />
    </div>
  );
}

export function WidgetError({ error }: { error: unknown }) {
  return <ErrorState error={error} compact />;
}

/** Shown when Azure has no data for a metric on this resource (never replaced by invented values). */
export function Unavailable({ message, reason }: { message?: string | null; reason?: string | null }) {
  return (
    <div
      className="flex h-full min-h-20 flex-col items-center justify-center gap-1 text-center text-muted-foreground"
      title={reason ? `Reason: ${reason}` : undefined}
    >
      <CircleSlash className="size-5" aria-hidden="true" />
      <p className="text-sm">Not available for this resource</p>
      {message ? <p className="max-w-xs text-xs">{message}</p> : null}
    </div>
  );
}
