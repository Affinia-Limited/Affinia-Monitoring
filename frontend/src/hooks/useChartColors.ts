import { useMemo } from "react";
import { useTheme } from "@/stores/theme";

const SERIES_VARS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--chart-6", "--chart-7", "--chart-8"];

// Split-series names with a semantic colour (HTTP status classes, WAF actions, health).
const SEMANTIC: Record<string, string> = {
  "2xx": "--status-healthy",
  "3xx": "--chart-1",
  "4xx": "--status-warning",
  "5xx": "--status-critical",
  Allow: "--status-healthy",
  Block: "--status-critical",
  Log: "--status-warning",
};

function read(name: string): string {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

/** Reads chart colours from CSS variables so charts follow light/dark mode. */
export function useChartColors() {
  const { resolved } = useTheme();
  return useMemo(() => {
    const palette = SERIES_VARS.map(read);
    return {
      palette,
      grid: read("--chart-grid"),
      axis: read("--muted-foreground"),
      tooltipBg: read("--popover"),
      tooltipBorder: read("--border"),
      forSeries: (name: string, index: number) => (SEMANTIC[name] ? read(SEMANTIC[name]) : palette[index % palette.length]),
      theme: resolved,
    };
  }, [resolved]);
}
