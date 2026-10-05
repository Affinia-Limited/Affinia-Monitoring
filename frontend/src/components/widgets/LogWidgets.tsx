import { ArrowRight } from "lucide-react";
import { LogResultsTable } from "@/components/LogResultsTable";
import { useLogQuery } from "@/hooks/useMetrics";
import type { LogQueryResult } from "@/types/api";
import { cn } from "@/utils/cn";
import { logToChart } from "./chartData";
import { TimeSeriesChart } from "./TimeSeriesChart";
import { configString, type WidgetProps } from "./types";
import { Unavailable, WidgetError, WidgetFrame, WidgetLoading } from "./WidgetFrame";

function useWidgetLog({ widget, resource }: WidgetProps) {
  return useLogQuery(resource.id, configString(widget, "query"));
}

function Notes({ result }: { result: LogQueryResult }) {
  if (!result.partial_error && !result.truncated) return null;
  return (
    <p className="mt-2 text-xs text-warning">
      {result.partial_error ? `Partial results: ${result.partial_error}` : "Results were truncated."}
    </p>
  );
}

export function LogTable(props: WidgetProps) {
  const query = useWidgetLog(props);
  return (
    <WidgetFrame title={props.widget.title}>
      {query.isLoading ? (
        <WidgetLoading />
      ) : query.isError ? (
        <WidgetError error={query.error} />
      ) : query.data ? (
        <>
          <LogResultsTable result={query.data} pageSize={10} maxHeight={320} />
          <Notes result={query.data} />
        </>
      ) : null}
    </WidgetFrame>
  );
}

export function LogChart(props: WidgetProps) {
  const query = useWidgetLog(props);
  const chart = query.data ? logToChart(query.data) : null;
  return (
    <WidgetFrame title={props.widget.title}>
      {query.isLoading ? (
        <WidgetLoading />
      ) : query.isError ? (
        <WidgetError error={query.error} />
      ) : chart ? (
        <TimeSeriesChart data={chart} kind="area" stacked={false} />
      ) : (
        <div className="h-[220px]">
          <Unavailable message="No time-series rows were returned for this time range." />
        </div>
      )}
    </WidgetFrame>
  );
}

/** Application map rendered as a list of edges (Source -> Target) with call and failure counts. */
export function DependencyMap(props: WidgetProps) {
  const query = useWidgetLog(props);
  const result = query.data;
  const idx = (name: string) => result?.columns.findIndex((c) => c.name.toLowerCase() === name.toLowerCase()) ?? -1;
  const edges = result
    ? result.rows.map((r) => ({
        source: String(r[idx("Source")] ?? "unknown"),
        target: String(r[idx("Target")] ?? "unknown"),
        type: String(r[idx("Type")] ?? ""),
        calls: Number(r[idx("Calls")] ?? 0),
        failed: Number(r[idx("Failed")] ?? 0),
        avg: r[idx("AvgDurationMs")],
      }))
    : [];
  return (
    <WidgetFrame title={props.widget.title} description="Calls between application roles and their dependencies">
      {query.isLoading ? (
        <WidgetLoading />
      ) : query.isError ? (
        <WidgetError error={query.error} />
      ) : edges.length === 0 ? (
        <Unavailable message="No dependency telemetry for this time range." />
      ) : (
        <ul className="divide-y divide-border">
          {edges.slice(0, 40).map((e, i) => {
            const failureRate = e.calls ? e.failed / e.calls : 0;
            return (
              <li key={i} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="rounded-md border border-border bg-muted px-2 py-0.5 font-medium">{e.source}</span>
                <ArrowRight className="size-4 text-muted-foreground" aria-label="calls" />
                <span className="rounded-md border border-border px-2 py-0.5">{e.target}</span>
                {e.type ? <span className="text-xs text-muted-foreground">{e.type}</span> : null}
                <span className="ml-auto tabular text-xs text-muted-foreground">
                  {e.calls.toLocaleString("en-GB")} calls
                  {typeof e.avg === "number" ? `, ${e.avg} ms avg` : ""}
                </span>
                <span className={cn("tabular text-xs", failureRate > 0.05 ? "text-critical" : failureRate > 0 ? "text-warning" : "text-healthy")}>
                  {e.failed.toLocaleString("en-GB")} failed
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </WidgetFrame>
  );
}
