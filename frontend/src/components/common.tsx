import { useState, type ReactNode } from "react";
import { cn } from "@/utils/cn";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Dialog, DialogContent } from "./ui/dialog";
import { ErrorState } from "./ui/states";

export function PageHeader({
  title,
  description,
  actions,
  badge,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
          {badge}
        </div>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function KpiCard({
  label,
  value,
  hint,
  tone,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "healthy" | "warning" | "critical" | "info";
  icon?: ReactNode;
}) {
  const accent = tone ? { healthy: "text-healthy", warning: "text-warning", critical: "text-critical", info: "text-info" }[tone] : "";
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
        <span className="truncate">{label}</span>
        {icon ? <span className={cn("[&_svg]:size-4", accent)}>{icon}</span> : null}
      </div>
      <div className={cn("tabular mt-2 text-2xl font-semibold", accent)}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
    </Card>
  );
}

export function ConfirmButton({
  title,
  description,
  confirmLabel = "Confirm",
  onConfirm,
  children,
  destructive = true,
  disabled,
}: {
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  onConfirm: () => Promise<unknown> | void;
  children: ReactNode;
  destructive?: boolean;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (busy) return;
        setOpen(o);
        setError(null);
      }}
    >
      <Button
        variant={destructive ? "outline" : "secondary"}
        size="sm"
        disabled={disabled}
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        {children}
      </Button>
      <DialogContent
        title={title}
        description={description}
        footer={
          <>
            <Button variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant={destructive ? "destructive" : "default"}
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await onConfirm();
                  setOpen(false);
                } catch (failure) {
                  // Keep the dialog open and say why, instead of failing silently.
                  setError(failure);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {confirmLabel}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">This action is recorded in the audit log.</p>
        {error ? <ErrorState error={error} compact className="mt-3" /> : null}
      </DialogContent>
    </Dialog>
  );
}

export function KeyValue({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{item.label}</dt>
          <dd className="mt-0.5 truncate text-sm">{item.value ?? "-"}</dd>
        </div>
      ))}
    </dl>
  );
}
