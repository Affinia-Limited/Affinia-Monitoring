import { CheckCircle2, AlertTriangle, X } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { cn } from "@/utils/cn";

interface Toast {
  id: number;
  title: string;
  description?: string;
  tone: "success" | "warning";
}

interface ToastApi {
  notify: (toast: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastApi>({ notify: () => {} });
let toastId = 0;

/** Minimal, accessible toasts (polite live region, auto-dismiss after 6 s). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const notify = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = ++toastId;
      setToasts((t) => [...t.slice(-2), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), 6000);
    },
    [dismiss],
  );
  const api = useMemo(() => ({ notify }), [notify]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((t) => {
          const Icon = t.tone === "success" ? CheckCircle2 : AlertTriangle;
          return (
            <div
              key={t.id}
              role="status"
              className="pointer-events-auto flex items-start gap-3 rounded-lg border border-border bg-popover p-3 text-sm text-popover-foreground shadow-lg"
            >
              <Icon className={cn("mt-0.5 size-4 shrink-0", t.tone === "success" ? "text-healthy" : "text-warning")} />
              <div className="min-w-0 flex-1">
                <p className="font-medium">{t.title}</p>
                {t.description ? <p className="mt-0.5 text-xs text-muted-foreground">{t.description}</p> : null}
              </div>
              <button type="button" className="text-muted-foreground hover:text-foreground" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
                <X className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
