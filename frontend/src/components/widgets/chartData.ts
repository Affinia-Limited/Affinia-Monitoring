import type { LogQueryResult, MetricOut } from "@/types/api";

export interface ChartSeries {
  key: string;
  name: string;
  unit: string;
}

export interface ChartData {
  rows: Record<string, number | null | string>[];
  series: ChartSeries[];
  unit: string;
}

/**
 * Merges metric series into rows keyed by timestamp for Recharts.
 * Unsplit metrics contribute one series each; a split metric contributes one series per dimension value.
 */
export function metricsToChart(metrics: MetricOut[]): ChartData {
  const byTime = new Map<string, Record<string, number | null | string>>();
  const series: ChartSeries[] = [];
  metrics.forEach((metric, mi) => {
    if (metric.unavailable_reason) return;
    const split = metric.series.length > 1 || Object.keys(metric.series[0]?.dimensions ?? {}).length > 0;
    metric.series.forEach((s, si) => {
      const key = `m${mi}_${si}`;
      series.push({ key, name: split ? s.name : metric.label, unit: metric.unit });
      for (const p of s.points) {
        const row = byTime.get(p.timestamp) ?? { t: p.timestamp, ts: Date.parse(p.timestamp) };
        row[key] = p.value;
        byTime.set(p.timestamp, row);
      }
    });
  });
  const rows = [...byTime.values()].sort((a, b) => Number(a.ts) - Number(b.ts));
  const units = new Set(series.map((s) => s.unit));
  return { rows, series, unit: units.size === 1 ? [...units][0] : "" };
}

const TIME_COLUMN = /^(timegenerated|timestamp)$/i;

/** Timechart from a log result: first datetime column is X, numeric columns are series. */
export function logToChart(result: LogQueryResult, unit = "count"): ChartData | null {
  const timeIndex = result.columns.findIndex((c) => c.type === "datetime" || TIME_COLUMN.test(c.name));
  if (timeIndex < 0 || result.rows.length === 0) return null;
  const numeric = result.columns
    .map((c, i) => ({ c, i }))
    .filter(({ i }) => i !== timeIndex && result.rows.some((r) => typeof r[i] === "number"));
  if (numeric.length === 0) return null;
  const rows = result.rows
    .map((r) => {
      const row: Record<string, number | null | string> = { t: String(r[timeIndex]), ts: Date.parse(String(r[timeIndex])) };
      numeric.forEach(({ i }) => {
        row[`c${i}`] = typeof r[i] === "number" ? (r[i] as number) : null;
      });
      return row;
    })
    .sort((a, b) => String(a.t).localeCompare(String(b.t)));
  return { rows, series: numeric.map(({ c, i }) => ({ key: `c${i}`, name: c.name, unit })), unit };
}
