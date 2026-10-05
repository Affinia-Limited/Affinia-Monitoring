import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { ApiError } from "@/api/client";
import { useChartColors } from "@/hooks/useChartColors";
import { useLogQuery } from "@/hooks/useMetrics";
import type { LogQueryResult } from "@/types/api";
import { formatValue } from "@/utils/format";
import { configString, type WidgetProps } from "./types";
import { Unavailable, WidgetError, WidgetFrame, WidgetLoading } from "./WidgetFrame";

/** "No logs yet" is a setup state, not a failure: say what to switch on instead of showing an error. */
export function LogQueryError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.code === "LOG_TABLE_NOT_FOUND") return <Unavailable message={error.message} />;
  return <WidgetError error={error} />;
}

function useWidgetLog({ widget, resource }: WidgetProps) {
  return useLogQuery(resource.id, configString(widget, "query"));
}

function unitOf(props: WidgetProps): string {
  return configString(props.widget, "unit") ?? "count";
}

function numericColumns(result: LogQueryResult): number[] {
  return result.columns.map((_, i) => i).filter((i) => result.rows.some((r) => typeof r[i] === "number"));
}

/** First text column (the category), e.g. Status, Route or Country. */
function labelColumn(result: LogQueryResult): number {
  return result.columns.findIndex((c, i) => c.type === "string" || result.rows.some((r) => typeof r[i] === "string"));
}

const SEMANTIC_NAMES: Record<string, "healthy" | "critical"> = {
  success: "healthy",
  succeeded: "healthy",
  ok: "healthy",
  failed: "critical",
  failure: "critical",
  errors: "critical",
};

/** A single headline value: the configured ``field`` of the first row, or its last numeric column. */
export function LogStat(props: WidgetProps) {
  const query = useWidgetLog(props);
  const result = query.data;
  const field = configString(props.widget, "field");
  let value: number | null = null;
  if (result?.rows.length) {
    const byName = field ? result.columns.findIndex((c) => c.name === field) : -1;
    const numeric = numericColumns(result);
    const index = byName >= 0 ? byName : numeric[numeric.length - 1];
    const raw = index !== undefined ? result.rows[0][index] : null;
    value = typeof raw === "number" ? raw : null;
  }
  const unit = unitOf(props);
  return (
    <WidgetFrame title={props.widget.title}>
      {query.isLoading ? (
        <WidgetLoading height={48} />
      ) : query.isError ? (
        <LogQueryError error={query.error} />
      ) : value === null ? (
        <p className="text-sm text-muted-foreground">No data for this time range.</p>
      ) : (
        <p className="tabular text-3xl font-semibold" aria-label={`${props.widget.title}: ${formatValue(value, unit)}`}>
          {unit === "none" ? value.toLocaleString("en-GB", { maximumFractionDigits: 2 }) : formatValue(value, unit)}
        </p>
      )}
    </WidgetFrame>
  );
}

/** Categories against values (status codes, routes, countries). Horizontal suits long labels. */
export function LogBar(props: WidgetProps) {
  const query = useWidgetLog(props);
  const colors = useChartColors();
  const result = query.data;
  const horizontal = props.widget.config.horizontal === true;
  const unit = unitOf(props);
  const label = result ? labelColumn(result) : -1;
  const numeric = result ? numericColumns(result) : [];
  const rows =
    result && label >= 0 && numeric.length
      ? result.rows.slice(0, 25).map((r) => {
          const row: Record<string, string | number> = { label: String(r[label] ?? "") };
          numeric.forEach((i) => (row[`c${i}`] = typeof r[i] === "number" ? (r[i] as number) : 0));
          return row;
        })
      : [];
  const height = horizontal ? Math.max(200, rows.length * 26 + 40) : 240;
  return (
    <WidgetFrame title={props.widget.title}>
      {query.isLoading ? (
        <WidgetLoading />
      ) : query.isError ? (
        <LogQueryError error={query.error} />
      ) : rows.length === 0 ? (
        <Unavailable message="No rows were returned for this time range." />
      ) : (
        <div style={{ height }} className="w-full" data-testid="log-bar-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
              <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" horizontal={!horizontal} vertical={horizontal} />
              {horizontal ? (
                <>
                  <XAxis type="number" tick={{ fill: colors.axis, fontSize: 11 }} tickFormatter={(v: number) => formatValue(v, unit)} />
                  <YAxis type="category" dataKey="label" width={180} tick={{ fill: colors.axis, fontSize: 11 }} interval={0} />
                </>
              ) : (
                <>
                  <XAxis dataKey="label" tick={{ fill: colors.axis, fontSize: 11 }} interval={0} />
                  <YAxis tick={{ fill: colors.axis, fontSize: 11 }} tickFormatter={(v: number) => formatValue(v, unit)} width={56} />
                </>
              )}
              <Tooltip
                cursor={{ fill: colors.grid, opacity: 0.4 }}
                contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 }}
                formatter={(v: number) => formatValue(v, unit)}
              />
              {numeric.map((i, n) => (
                <Bar key={i} dataKey={`c${i}`} name={result?.columns[i].name} fill={colors.forSeries(result?.columns[i].name ?? "", n)} radius={2} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </WidgetFrame>
  );
}

/** Share of a whole: the numeric columns of one row (Success / Failed), or category/value rows. */
export function LogPie(props: WidgetProps) {
  const query = useWidgetLog(props);
  const colors = useChartColors();
  const result = query.data;
  const unit = unitOf(props);
  let slices: { name: string; value: number }[] = [];
  if (result?.rows.length) {
    const label = labelColumn(result);
    const numeric = numericColumns(result);
    slices =
      label >= 0 && numeric.length
        ? result.rows.map((r) => ({ name: String(r[label]), value: Number(r[numeric[0]] ?? 0) }))
        : numeric.map((i) => ({ name: result.columns[i].name, value: Number(result.rows[0][i] ?? 0) }));
  }
  const total = slices.reduce((s, x) => s + x.value, 0);
  const colour = (name: string, i: number) => {
    const semantic = SEMANTIC_NAMES[name.toLowerCase()];
    return semantic === "healthy" ? colors.forSeries("2xx", i) : semantic === "critical" ? colors.forSeries("5xx", i) : colors.forSeries(name, i);
  };
  return (
    <WidgetFrame title={props.widget.title}>
      {query.isLoading ? (
        <WidgetLoading />
      ) : query.isError ? (
        <LogQueryError error={query.error} />
      ) : total === 0 ? (
        <Unavailable message="No requests in this time range." />
      ) : (
        <div className="flex items-center gap-4">
          <div className="h-[140px] w-[140px] shrink-0" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={slices} dataKey="value" nameKey="name" innerRadius={42} outerRadius={64} strokeWidth={1}>
                  {slices.map((s, i) => (
                    <Cell key={s.name} fill={colour(s.name, i)} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="min-w-0 flex-1 space-y-1.5 text-sm">
            {slices.map((s, i) => (
              <li key={s.name} className="flex items-center gap-2">
                <span className="inline-block size-2.5 shrink-0 rounded-full" style={{ background: colour(s.name, i) }} aria-hidden="true" />
                <span className="truncate text-muted-foreground">{s.name}</span>
                <span className="tabular ml-auto font-medium">{formatValue(s.value, unit)}</span>
                <span className="tabular w-12 text-right text-xs text-muted-foreground">{((s.value / total) * 100).toFixed(1)}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </WidgetFrame>
  );
}

/** Section heading and guidance, like a Grafana text panel. */
export function Note({ widget }: WidgetProps) {
  return (
    <div className="pt-1" data-testid="widget">
      {widget.title ? <h3 className="text-base font-semibold">{widget.title}</h3> : null}
      {configString(widget, "text") ? <p className="mt-0.5 text-sm text-muted-foreground">{configString(widget, "text")}</p> : null}
    </div>
  );
}
