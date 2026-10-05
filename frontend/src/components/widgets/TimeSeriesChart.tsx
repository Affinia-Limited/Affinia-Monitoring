import type { ReactElement } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useChartColors } from "@/hooks/useChartColors";
import { formatAxisTime, formatAxisValue, formatDateTime, formatValue } from "@/utils/format";
import type { ChartData } from "./chartData";

export type ChartKind = "line" | "area" | "bar";

interface TooltipEntry {
  dataKey?: string | number;
  name?: string;
  value?: number | string | null;
  color?: string;
}

function ChartTooltip({
  active,
  payload,
  label,
  unitOf,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: number | string;
  unitOf: (key: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <p className="mb-1 font-medium">{formatDateTime(new Date(Number(label)))}</p>
      <ul className="space-y-0.5">
        {payload.map((p) => (
          <li key={String(p.dataKey)} className="flex items-center gap-2">
            <span className="inline-block size-2 rounded-full" style={{ background: p.color }} aria-hidden="true" />
            <span className="text-muted-foreground">{p.name}</span>
            <span className="tabular ml-auto pl-3 font-medium">
              {p.value === null || p.value === undefined ? "No data" : formatValue(Number(p.value), unitOf(String(p.dataKey)))}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * One chart component for every time-series widget; the widget only chooses the kind.
 * Axes, grid, legend and tooltip are passed as direct children (Recharts does not look
 * inside fragments). Null points are left as gaps, never drawn as zero.
 */
export function TimeSeriesChart({
  data,
  kind,
  stacked,
  height = 240,
}: {
  data: ChartData;
  kind: ChartKind;
  stacked?: boolean;
  height?: number;
}) {
  const colors = useChartColors();
  const times = data.rows.map((r) => Number(r.ts)).filter(Number.isFinite);
  const span = times.length > 1 ? times[times.length - 1] - times[0] : 0;
  const unitOf = (key: string) => data.series.find((s) => s.key === key)?.unit ?? data.unit;
  const yUnit = data.unit || data.series[0]?.unit || "count";
  const multi = data.series.length > 1;

  const decorations: ReactElement[] = [
    <CartesianGrid key="grid" stroke={colors.grid} strokeDasharray="0" vertical={false} />,
    <XAxis
      key="x"
      dataKey="ts"
      type={kind === "bar" ? "category" : "number"}
      scale={kind === "bar" ? "auto" : "time"}
      domain={["dataMin", "dataMax"]}
      tickFormatter={(v: number) => formatAxisTime(v, span)}
      tick={{ fill: colors.axis, fontSize: 11 }}
      axisLine={{ stroke: colors.grid }}
      tickLine={false}
      minTickGap={40}
      tickMargin={6}
    />,
    <YAxis
      key="y"
      tickFormatter={(v: number) => formatAxisValue(v, yUnit)}
      tick={{ fill: colors.axis, fontSize: 11 }}
      axisLine={false}
      tickLine={false}
      width={60}
      allowDecimals
    />,
    <Tooltip
      key="tooltip"
      cursor={kind === "bar" ? { fill: colors.grid, opacity: 0.5 } : { stroke: colors.axis, strokeDasharray: "3 3" }}
      content={<ChartTooltip unitOf={unitOf} />}
    />,
  ];
  if (multi) {
    decorations.push(
      <Legend key="legend" verticalAlign="bottom" wrapperStyle={{ fontSize: 12, paddingTop: 8 }} iconType="circle" iconSize={8} />,
    );
  }

  const common = { data: data.rows, margin: { top: 8, right: 12, bottom: 0, left: 0 } };

  return (
    <div style={{ height: multi ? height + 24 : height }} className="w-full" data-testid="time-series-chart">
      <ResponsiveContainer width="100%" height="100%">
        {kind === "bar" ? (
          <BarChart {...common}>
            {decorations}
            {data.series.map((s, i) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.name}
                stackId={stacked ? "a" : undefined}
                fill={colors.forSeries(s.name, i)}
                isAnimationActive={false}
                maxBarSize={28}
              />
            ))}
          </BarChart>
        ) : kind === "area" ? (
          <AreaChart {...common}>
            {decorations}
            {data.series.map((s, i) => (
              <Area
                key={s.key}
                dataKey={s.key}
                name={s.name}
                type="monotone"
                stackId={stacked ? "a" : undefined}
                stroke={colors.forSeries(s.name, i)}
                fill={colors.forSeries(s.name, i)}
                fillOpacity={0.16}
                strokeWidth={1.6}
                dot={false}
                activeDot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        ) : (
          <LineChart {...common}>
            {decorations}
            {data.series.map((s, i) => (
              <Line
                key={s.key}
                dataKey={s.key}
                name={s.name}
                type="monotone"
                stroke={colors.forSeries(s.name, i)}
                strokeWidth={1.8}
                dot={false}
                activeDot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
