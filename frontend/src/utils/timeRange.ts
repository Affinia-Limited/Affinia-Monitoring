import type { TimeRangePreset } from "@/types/api";

export interface TimeRangeValue {
  preset: TimeRangePreset;
  start?: string;
  end?: string;
}

export const TIME_RANGE_OPTIONS: { value: TimeRangePreset; label: string }[] = [
  { value: "30m", label: "Last 30 minutes" },
  { value: "1h", label: "Last 1 hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "custom", label: "Custom" },
];

const DURATIONS: Record<Exclude<TimeRangePreset, "custom">, number> = {
  "30m": 30 * 60_000,
  "1h": 3600_000,
  "6h": 6 * 3600_000,
  "24h": 24 * 3600_000,
  "7d": 7 * 24 * 3600_000,
  "30d": 30 * 24 * 3600_000,
};

export function isPreset(value: string | null | undefined): value is TimeRangePreset {
  return !!value && TIME_RANGE_OPTIONS.some((o) => o.value === value);
}

export function timeRangeLabel(range: TimeRangeValue): string {
  if (range.preset !== "custom") return TIME_RANGE_OPTIONS.find((o) => o.value === range.preset)?.label ?? range.preset;
  const fmt = (v?: string) =>
    v ? new Date(v).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" }) : "?";
  return `${fmt(range.start)} - ${fmt(range.end)}`;
}

export function rangeSpanMs(range: TimeRangeValue): number {
  if (range.preset === "custom") {
    if (!range.start || !range.end) return DURATIONS["24h"];
    return Math.max(0, new Date(range.end).getTime() - new Date(range.start).getTime());
  }
  return DURATIONS[range.preset];
}

/** Query-string parameters in the backend's format (timeRange, start, end). */
export function timeRangeParams(range: TimeRangeValue): Record<string, string> {
  if (range.preset === "custom") {
    if (!range.start || !range.end) return { timeRange: "24h" };
    return { timeRange: "custom", start: new Date(range.start).toISOString(), end: new Date(range.end).toISOString() };
  }
  return { timeRange: range.preset };
}

/** Validates a custom range; returns an error message or null. */
export function validateCustomRange(start?: string, end?: string): string | null {
  if (!start || !end) return "Choose both a start and an end.";
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  if (Number.isNaN(s) || Number.isNaN(e)) return "Enter valid dates.";
  if (e <= s) return "The end must be after the start.";
  if (e - s > 93 * 24 * 3600_000) return "Custom ranges are limited to 93 days.";
  return null;
}
