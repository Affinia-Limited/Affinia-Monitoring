import { Braces, ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import type { LogQueryResult } from "@/types/api";
import { formatDateTime } from "@/utils/format";
import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";

function cell(value: unknown, type: string): string {
  if (value === null || value === undefined) return "";
  if (type === "datetime" && typeof value === "string") return formatDateTime(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Sticky-header, paginated table of log rows with a raw JSON view per row. */
export function LogResultsTable({
  result,
  pageSize = 50,
  maxHeight = 420,
}: {
  result: LogQueryResult;
  pageSize?: number;
  maxHeight?: number;
}) {
  const [page, setPage] = useState(0);
  const [raw, setRaw] = useState<Record<string, unknown> | null>(null);
  const pages = Math.max(1, Math.ceil(result.rows.length / pageSize));
  const rows = useMemo(() => result.rows.slice(page * pageSize, (page + 1) * pageSize), [result.rows, page, pageSize]);

  if (result.rows.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">The query returned no rows for this time range.</p>;
  }

  return (
    <div>
      <div className="scrollbar-thin overflow-auto rounded-md border border-border" style={{ maxHeight }}>
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-muted text-left text-muted-foreground">
            <tr>
              <th className="w-8 px-2 py-2" aria-label="Row actions" />
              {result.columns.map((c) => (
                <th key={c.name} scope="col" className="px-2 py-2 font-medium whitespace-nowrap">
                  {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono">
            {rows.map((row, ri) => (
              <tr key={ri} className="border-t border-border hover:bg-muted/40">
                <td className="px-2 py-1.5">
                  <button
                    type="button"
                    className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                    aria-label="View raw row"
                    onClick={() => setRaw(Object.fromEntries(result.columns.map((c, i) => [c.name, row[i]])))}
                  >
                    <Braces className="size-3.5" />
                  </button>
                </td>
                {result.columns.map((c, ci) => (
                  <td key={c.name} className="max-w-md truncate px-2 py-1.5 whitespace-nowrap" title={cell(row[ci], c.type)}>
                    {cell(row[ci], c.type)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {result.rows.length.toLocaleString("en-GB")} rows{result.truncated ? " (truncated)" : ""}
        </span>
        {pages > 1 ? (
          <div className="flex items-center gap-1">
            <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)}>
              <ChevronLeft />
            </Button>
            <span>
              Page {page + 1} of {pages}
            </span>
            <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
              <ChevronRight />
            </Button>
          </div>
        ) : null}
      </div>
      <Dialog open={raw !== null} onOpenChange={(o) => !o && setRaw(null)}>
        {raw ? (
          <DialogContent title="Raw row" className="max-w-2xl">
            <pre className="scrollbar-thin overflow-auto rounded-md bg-muted p-3 font-mono text-xs">{JSON.stringify(raw, null, 2)}</pre>
          </DialogContent>
        ) : null}
      </Dialog>
    </div>
  );
}
