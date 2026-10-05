import { Line, LineChart, ResponsiveContainer } from "recharts";
import { useChartColors } from "@/hooks/useChartColors";
import { useMetrics } from "@/hooks/useMetrics";
import type { MetricOut } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatValue } from "@/utils/format";
import { metricsToChart } from "./chartData";
import { levelColour, thresholdLevel, type Thresholds, widgetThresholds } from "./thresholds";
import { type ChartKind, TimeSeriesChart } from "./TimeSeriesChart";
import { configString, configStrings, type WidgetProps } from "./types";
import { Unavailable, WidgetError, WidgetFrame, WidgetLoading } from "./WidgetFrame";

type Reducer = "avg" | "sum" | "max" | "min" | "latest";

function reduced(metric: MetricOut, reducer: Reducer): number | null {
  const value = metric.summary[reducer];
  return value === undefined ? null : value;
}

/** Presentational metric tile, exported for reuse and tests. */
export function MetricValue({
  metric,
  reducer,
  title,
  thresholds = null,
}: {
  metric: MetricOut;
  reducer: Reducer;
  title?: string;
  thresholds?: Thresholds | null;
}) {
  const colors = useChartColors();
  if (metric.unavailable_reason) {
    return <Unavailable message={metric.unavailable_message} reason={metric.unavailable_reason} />;
  }
  const points = (metric.series[0]?.points ?? []).map((p) => ({ v: p.value }));
  const value = reduced(metric, reducer);
  const level = thresholdLevel(value, thresholds);
  return (
    <div>
      <div
        className="tabular text-2xl font-semibold"
        aria-label={title ?? metric.label}
        data-level={level ?? "none"}
        style={level && level !== "healthy" ? { color: levelColour(level) } : undefined}
      >
        {formatValue(value, metric.unit)}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">
        {reducer === "sum" ? "Total" : reducer === "max" ? "Peak" : reducer === "latest" ? "Latest" : "Average"} over
        range
      </div>
      {points.length > 1 ? (
        <div className="mt-2 h-10" aria-hidden="true">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points}>
              <Line dataKey="v" stroke={colors.palette[0]} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : null}
    </div>
  );
}

export function MetricCard({ widget, resource }: WidgetProps) {
  const key = configString(widget, "metric");
  const reducer = (configString(widget, "reducer") ?? "avg") as Reducer;
  const query = useMetrics(resource.id, key ? [key] : []);
  const metric = query.data?.metrics[0];
  return (
    <WidgetFrame title={widget.title}>
      {query.isLoading ? (
        <WidgetLoading height={60} />
      ) : query.isError ? (
        <WidgetError error={query.error} />
      ) : metric ? (
        <MetricValue metric={metric} reducer={reducer} title={widget.title} thresholds={widgetThresholds(widget)} />
      ) : (
        <Unavailable />
      )}
    </WidgetFrame>
  );
}

export function Gauge({ widget, resource }: WidgetProps) {
  const key = configString(widget, "metric");
  const max = typeof widget.config.max === "number" ? widget.config.max : 100;
  const query = useMetrics(resource.id, key ? [key] : []);
  const metric = query.data?.metrics[0];
  const value = metric && !metric.unavailable_reason ? metric.summary.avg ?? null : null;
  const ratio = value === null ? 0 : Math.max(0, Math.min(1, value / max));
  const r = 42;
  const circumference = Math.PI * r;
  // Colour comes only from the metric's health thresholds; without them the gauge is neutral.
  const level = thresholdLevel(value, widgetThresholds(widget));
  return (
    <WidgetFrame title={widget.title}>
      {query.isLoading ? (
        <WidgetLoading height={80} />
      ) : query.isError ? (
        <WidgetError error={query.error} />
      ) : !metric || metric.unavailable_reason || value === null ? (
        <Unavailable message={metric?.unavailable_message} reason={metric?.unavailable_reason} />
      ) : (
        <div className="flex flex-col items-center">
          <svg viewBox="0 0 100 58" className="w-full max-w-40" role="img" aria-label={`${widget.title} ${formatValue(value, metric.unit)}`}>
            <path d="M 8 50 A 42 42 0 0 1 92 50" fill="none" stroke="var(--muted)" strokeWidth="9" strokeLinecap="round" />
            <path
              d="M 8 50 A 42 42 0 0 1 92 50"
              fill="none"
              stroke={levelColour(level)}
              data-testid="gauge-arc"
              data-level={level ?? "none"}
              strokeWidth="9"
              strokeLinecap="round"
              strokeDasharray={`${circumference * ratio} ${circumference}`}
            />
          </svg>
          <div className="tabular -mt-6 text-xl font-semibold">{formatValue(value, metric.unit)}</div>
          <div className="text-xs text-muted-foreground">Average, peak {formatValue(metric.summary.max ?? null, metric.unit)}</div>
        </div>
      )}
    </WidgetFrame>
  );
}

function SeriesChartWidget({ widget, resource, kind }: WidgetProps & { kind: ChartKind }) {
  const keys = configStrings(widget, "metrics");
  const stacked = widget.config.stacked === true;
  const query = useMetrics(resource.id, keys);
  const metrics = query.data?.metrics ?? [];
  const chart = metricsToChart(metrics);
  const unavailable = metrics.filter((m) => m.unavailable_reason);
  return (
    <WidgetFrame title={widget.title}>
      {query.isLoading ? (
        <WidgetLoading />
      ) : query.isError ? (
        <WidgetError error={query.error} />
      ) : chart.series.length === 0 ? (
        <div className="h-[220px]">
          <Unavailable message={unavailable[0]?.unavailable_message} reason={unavailable[0]?.unavailable_reason} />
        </div>
      ) : (
        <>
          <TimeSeriesChart data={chart} kind={kind} stacked={stacked} />
          {unavailable.length > 0 ? (
            <p className={cn("mt-2 text-xs text-muted-foreground")}>
              Not available: {unavailable.map((m) => m.label).join(", ")}
            </p>
          ) : null}
        </>
      )}
    </WidgetFrame>
  );
}

export const LineChartWidget = (props: WidgetProps) => <SeriesChartWidget {...props} kind="line" />;
export const AreaChartWidget = (props: WidgetProps) => <SeriesChartWidget {...props} kind="area" />;
export const BarChartWidget = (props: WidgetProps) => <SeriesChartWidget {...props} kind="bar" />;
