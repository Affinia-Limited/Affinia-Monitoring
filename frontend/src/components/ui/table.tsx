import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "@/utils/cn";

/** Every data table scrolls horizontally inside its card instead of overflowing the page. */
export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="scrollbar-thin w-full max-w-full overflow-x-auto" role="region" aria-label="Scrollable table" tabIndex={0}>
      <table className={cn("w-full border-collapse text-sm", className)} {...props} />
    </div>
  );
}

export function THead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("border-b border-border text-left text-xs text-muted-foreground", className)} {...props} />;
}

export function TR({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("border-b border-border/70 last:border-0", className)} {...props} />;
}

export function TH({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th scope="col" className={cn("h-10 px-3 font-medium whitespace-nowrap first:pl-5 last:pr-5", className)} {...props} />;
}

export function TD({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("tabular h-11 px-3 py-2 align-middle first:pl-5 last:pr-5", className)} {...props} />;
}

/** Hide low-priority columns on tablet and smaller; apply to both the TH and the TD. */
export const LG_ONLY = "hidden lg:table-cell";
