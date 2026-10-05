import type { ReactNode } from "react";
import { cn } from "@/utils/cn";

export interface ChipOption<T extends string> {
  value: T;
  label: ReactNode;
  count?: number;
}

/** A single-choice filter row, e.g. [All] [Healthy] [Warning] [Critical]. Keyboard accessible buttons. */
export function FilterChips<T extends string>({
  label,
  options,
  value,
  onChange,
  className,
}: {
  /** Accessible name for the group. */
  label: string;
  options: ChipOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={cn("flex flex-wrap gap-1.5", className)}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors",
              active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {o.label}
            {o.count !== undefined ? <span className={cn("tabular", active ? "opacity-80" : "")}>{o.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
