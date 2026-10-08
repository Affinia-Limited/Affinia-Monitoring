import { cn } from "@/utils/cn";

/**
 * Tiny inline trend line. Gaps (null values) break the line rather than being drawn as zero.
 * Colour comes from ``currentColor``, so set it with a text colour class.
 */
export function Sparkline({
  values,
  label,
  width = 96,
  height = 24,
  className,
}: {
  values: (number | null)[];
  label: string;
  width?: number;
  height?: number;
  className?: string;
}) {
  const present = values.filter((v): v is number => v !== null);
  if (present.length < 2) {
    return <span className={cn("inline-block text-xs text-muted-foreground", className)} style={{ width }} aria-label={label}>No data</span>;
  }
  const min = Math.min(...present);
  const max = Math.max(...present);
  const span = max - min || 1;
  const pad = 2;
  const x = (i: number) => (values.length === 1 ? width / 2 : (i / (values.length - 1)) * width);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);

  let d = "";
  let pen = false;
  values.forEach((v, i) => {
    if (v === null) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  let lastIndex = values.length - 1;
  while (values[lastIndex] === null) lastIndex -= 1;
  const last = values[lastIndex] as number;

  return (
    <svg role="img" aria-label={label} width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn("shrink-0 overflow-visible", className)}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(lastIndex)} cy={y(last)} r={2} fill="currentColor" />
    </svg>
  );
}
