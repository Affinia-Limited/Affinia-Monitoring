const dateTime = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const timeOnly = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
const dayMonth = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "2-digit" });
const compact = new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 });
const plain = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

/** DD/MM/YYYY HH:mm */
export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "-";
  const d = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(d.getTime())) return "-";
  return dateTime.format(d).replace(",", "");
}

/** Axis label: HH:mm up to 24h, DD/MM HH:mm up to 7 days, DD/MM beyond. */
export function formatAxisTime(value: string | number, spanMs: number): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  if (spanMs <= 24 * 3600_000 + 60_000) return timeOnly.format(d);
  if (spanMs <= 7 * 24 * 3600_000 + 60_000) return `${dayMonth.format(d)} ${timeOnly.format(d)}`;
  return dayMonth.format(d);
}

/** Compact axis tick in the metric's unit (e.g. 40%, 120 ms, 1.2 GB, 12K). */
export function formatAxisValue(value: number, unit: string): string {
  if (!Number.isFinite(value)) return "";
  switch (unit) {
    case "percent":
      return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
    case "milliseconds":
    case "seconds":
    case "bytes":
    case "bytes_per_second":
      return formatValue(value, unit);
    default:
      return Math.abs(value) >= 1000 ? compact.format(value).toUpperCase() : plain.format(value);
  }
}

export function formatRelative(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return "never";
  const d = new Date(value);
  const seconds = Math.round((now.getTime() - d.getTime()) / 1000);
  if (Number.isNaN(seconds)) return "-";
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export function formatBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let v = Math.abs(value);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${value < 0 ? "-" : ""}${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function formatDuration(ms: number): string {
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

/** Format a metric value in the platform's unit vocabulary. */
export function formatValue(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  switch (unit) {
    case "percent":
      return `${value >= 10 ? value.toFixed(0) : value.toFixed(value >= 1 ? 1 : 2)}%`;
    case "milliseconds":
      return formatDuration(value);
    case "seconds":
      return formatDuration(value * 1000);
    case "bytes":
      return formatBytes(value);
    case "bytes_per_second":
      return `${formatBytes(value)}/s`;
    case "count":
    case "countps":
      return Math.abs(value) >= 10_000 ? compact.format(value).toUpperCase() : plain.format(Math.round(value * 100) / 100);
    default:
      return plain.format(value);
  }
}

export function titleCase(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

const REGIONS: Record<string, string> = {
  uksouth: "UK South",
  ukwest: "UK West",
  westeurope: "West Europe",
  northeurope: "North Europe",
  eastus: "East US",
  eastus2: "East US 2",
  westus: "West US",
  global: "Global",
};

export function regionName(location: string | null | undefined): string {
  if (!location) return "-";
  return REGIONS[location] ?? location;
}
