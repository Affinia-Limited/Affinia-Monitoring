import { useMutation, useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { PageHeader } from "@/components/common";
import { LogResultsTable } from "@/components/LogResultsTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { logToChart } from "@/components/widgets/chartData";
import { TimeSeriesChart } from "@/components/widgets/TimeSeriesChart";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { useFilters } from "@/stores/filters";
import type { PredefinedQuery } from "@/types/api";
import { cn } from "@/utils/cn";
import { timeRangeLabel } from "@/utils/timeRange";

const SEVERITIES = ["Critical", "Error", "Warning", "Informational", "Verbose"];

function KqlEditor({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled: boolean }) {
  const lines = Math.max(6, value.split("\n").length);
  return (
    <div className={cn("flex overflow-hidden rounded-md border border-input bg-card font-mono text-xs", disabled && "opacity-70")}>
      <div aria-hidden="true" className="select-none border-r border-border bg-muted px-2 py-2 text-right text-muted-foreground">
        {Array.from({ length: lines }, (_, i) => (
          <div key={i} className="leading-5">
            {i + 1}
          </div>
        ))}
      </div>
      <textarea
        aria-label="KQL query"
        className="min-h-32 flex-1 resize-y bg-transparent px-3 py-2 leading-5 outline-none"
        spellCheck={false}
        rows={lines}
        value={value}
        readOnly={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function LogsPage() {
  const [params, setParams] = useSearchParams();
  const { timeRange } = useFilters();
  const canKql = usePermission(PERMISSIONS.runKql);
  const targetId = params.get("resource") ?? "";
  const [selected, setSelected] = useState<PredefinedQuery | null>(null);
  const [kql, setKql] = useState("");
  const [search, setSearch] = useState("");
  const [severities, setSeverities] = useState<string[]>([]);

  const targets = useQuery({ queryKey: ["log-targets"], queryFn: endpoints.logTargets });
  const queries = useQuery({
    queryKey: ["log-queries", targetId],
    queryFn: () => endpoints.logQueries(targetId),
    enabled: !!targetId,
  });
  const run = useMutation({ mutationFn: endpoints.runLogQuery });

  const grouped = useMemo(() => {
    const map = new Map<string, PredefinedQuery[]>();
    for (const q of queries.data ?? []) map.set(q.category, [...(map.get(q.category) ?? []), q]);
    return [...map.entries()];
  }, [queries.data]);

  const edited = selected ? kql.trim() !== selected.kql.trim() : kql.trim().length > 0;
  const execute = () => {
    if (!targetId) return;
    run.mutate({
      resource_id: targetId,
      query_key: edited ? null : selected?.key,
      kql: edited ? kql : null,
      time_range: timeRange.preset,
      start: timeRange.preset === "custom" ? timeRange.start : null,
      end: timeRange.preset === "custom" ? timeRange.end : null,
      search: search.trim() || null,
      severities: !edited && selected?.supports_severity ? severities : [],
    });
  };
  const chart = run.data ? logToChart(run.data) : null;
  const showChart = !!chart && (run.data?.visualization === "timechart" || chart.rows.length > 1);

  return (
    <>
      <PageHeader title="Logs" description="Log Analytics and Application Insights queries, scoped to one resource at a time" />
      <div className="grid grid-cols-12 gap-4">
        <Card className="col-span-12 lg:col-span-4 xl:col-span-3">
          <CardHeader title="Target" />
          <CardContent className="space-y-4">
            <Field label="Resource or workspace" htmlFor="log-target">
              <Select
                id="log-target"
                value={targetId}
                onChange={(e) => {
                  setSelected(null);
                  setKql("");
                  run.reset();
                  setParams(
                    (prev) => {
                      const next = new URLSearchParams(prev);
                      if (e.target.value) next.set("resource", e.target.value);
                      else next.delete("resource");
                      return next;
                    },
                    { replace: true },
                  );
                }}
              >
                <option value="">Select a target</option>
                {targets.data?.map((t) => (
                  <option key={t.resource_id} value={t.resource_id}>
                    {t.name} ({t.type_display_name}
                    {t.environment_name ? `, ${t.environment_name}` : ""})
                  </option>
                ))}
              </Select>
            </Field>
            {targets.isError ? <ErrorState error={targets.error} compact /> : null}
            {queries.isLoading ? <LoadingBlock /> : null}
            {grouped.map(([category, items]) => (
              <div key={category}>
                <p className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{category}</p>
                <ul className="space-y-0.5">
                  {items.map((q) => (
                    <li key={q.key}>
                      <button
                        type="button"
                        className={cn(
                          "w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted",
                          selected?.key === q.key && "bg-accent text-accent-foreground",
                        )}
                        onClick={() => {
                          setSelected(q);
                          setKql(q.kql);
                          setSeverities([]);
                        }}
                      >
                        {q.title}
                        {q.target !== "self" ? <span className="block text-xs text-muted-foreground">Runs on the linked component</span> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </CardContent>
        </Card>

        <div className="col-span-12 space-y-4 lg:col-span-8 xl:col-span-9">
          <Card>
            <CardHeader
              title={selected?.title ?? "Query"}
              description={selected?.description || `Time range: ${timeRangeLabel(timeRange)} (change it in the top bar)`}
            />
            <CardContent className="space-y-3">
              <KqlEditor value={kql} onChange={setKql} disabled={!canKql} />
              {!canKql ? (
                <p className="text-xs text-muted-foreground">Your role can run predefined queries. Editing KQL requires the Operator role or higher.</p>
              ) : edited ? (
                <p className="text-xs text-muted-foreground">
                  Custom KQL is validated, runs only against the selected resource, and is recorded in the audit log.
                </p>
              ) : null}
              <div className="flex flex-wrap items-end gap-3">
                <Field label="Search" htmlFor="log-search" className="min-w-56 flex-1">
                  <Input id="log-search" value={search} placeholder="Filter rows containing text" onChange={(e) => setSearch(e.target.value)} />
                </Field>
                {selected?.supports_severity && !edited ? (
                  <fieldset className="space-y-1">
                    <legend className="text-xs font-medium">Severity</legend>
                    <div className="flex flex-wrap gap-2">
                      {SEVERITIES.map((s) => (
                        <label key={s} className="flex items-center gap-1 text-xs">
                          <input
                            type="checkbox"
                            checked={severities.includes(s)}
                            onChange={(e) => setSeverities(e.target.checked ? [...severities, s] : severities.filter((x) => x !== s))}
                          />
                          {s}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                ) : null}
                <Button onClick={execute} disabled={!targetId || run.isPending || (!selected && !(canKql && kql.trim()))}>
                  <Play /> {run.isPending ? "Running..." : "Run query"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {run.isError ? <ErrorState error={run.error} /> : null}
          {run.data ? (
            <Card>
              <CardHeader
                title="Results"
                description={`${run.data.row_count.toLocaleString("en-GB")} rows`}
              />
              <CardContent className="space-y-3">
                {run.data.partial_error ? (
                  <p className="rounded-md border border-warning/40 bg-warning/10 p-2 text-xs">Partial results: {run.data.partial_error}</p>
                ) : null}
                {run.data.truncated ? (
                  <p className="rounded-md border border-warning/40 bg-warning/10 p-2 text-xs">
                    The result was truncated to the maximum row count. Narrow the query or time range.
                  </p>
                ) : null}
                {showChart && chart ? <TimeSeriesChart data={chart} kind="line" /> : null}
                <LogResultsTable result={run.data} />
                <details>
                  <summary className="cursor-pointer text-xs text-muted-foreground">Executed query</summary>
                  <pre className="mt-2 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">{run.data.query}</pre>
                </details>
              </CardContent>
            </Card>
          ) : !run.isError ? (
            <Card>
              <EmptyState
                title={targetId ? "Choose a query and run it" : "Select a resource to query"}
                description="Queries are executed resource-centric, so only logs emitted by the selected resource are returned."
              />
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}
