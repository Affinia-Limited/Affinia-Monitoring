import { CheckCircle2, Circle, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { SyncRun, SyncStep } from "@/types/api";
import { cn } from "@/utils/cn";

const ICONS: Record<SyncStep["status"], { icon: typeof Circle; className: string; label: string }> = {
  pending: { icon: Circle, className: "text-muted-foreground", label: "Pending" },
  running: { icon: Loader2, className: "animate-spin text-info", label: "In progress" },
  succeeded: { icon: CheckCircle2, className: "text-healthy", label: "Done" },
  failed: { icon: XCircle, className: "text-critical", label: "Failed" },
  skipped: { icon: MinusCircle, className: "text-muted-foreground", label: "Skipped" },
};

export function SyncProgress({ run }: { run: SyncRun }) {
  return (
    <ol className="space-y-2" aria-label="Synchronisation progress" aria-live="polite">
      {run.steps.map((step) => {
        const meta = ICONS[step.status] ?? ICONS.pending;
        const Icon = meta.icon;
        return (
          <li key={step.key} className="flex items-start gap-3" data-status={step.status}>
            <Icon className={cn("mt-0.5 size-4 shrink-0", meta.className)} aria-label={meta.label} />
            <div className="min-w-0">
              <p className={cn("text-sm", step.status === "pending" && "text-muted-foreground")}>{step.label}</p>
              {step.detail ? <p className="text-xs text-muted-foreground">{step.detail}</p> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
