import { CalendarClock } from "lucide-react";
import { useState } from "react";
import { useFilters } from "@/stores/filters";
import { TIME_RANGE_OPTIONS, timeRangeLabel, validateCustomRange } from "@/utils/timeRange";
import { Button } from "./ui/button";
import { Field, Input } from "./ui/form";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/menu";

function toLocalInput(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function TimeRangePicker() {
  const { timeRange, setTimeRange } = useFilters();
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(toLocalInput(timeRange.start));
  const [end, setEnd] = useState(toLocalInput(timeRange.end));
  const [error, setError] = useState<string | null>(null);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" aria-label="Time range">
          <CalendarClock />
          <span className="hidden sm:inline">{timeRangeLabel(timeRange)}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72">
        <div className="grid grid-cols-2 gap-1" role="listbox" aria-label="Time range presets">
          {TIME_RANGE_OPTIONS.filter((o) => o.value !== "custom").map((o) => (
            <Button
              key={o.value}
              size="sm"
              variant={timeRange.preset === o.value ? "default" : "ghost"}
              className="justify-start"
              role="option"
              aria-selected={timeRange.preset === o.value}
              onClick={() => {
                setTimeRange({ preset: o.value });
                setOpen(false);
              }}
            >
              {o.label}
            </Button>
          ))}
        </div>
        <div className="mt-3 space-y-2 border-t border-border pt-3">
          <p className="text-xs font-medium">Custom range</p>
          <Field label="Start" htmlFor="tr-start">
            <Input id="tr-start" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="End" htmlFor="tr-end" error={error}>
            <Input id="tr-end" type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
          </Field>
          <Button
            size="sm"
            className="w-full"
            onClick={() => {
              const problem = validateCustomRange(start, end);
              setError(problem);
              if (problem) return;
              setTimeRange({ preset: "custom", start: new Date(start).toISOString(), end: new Date(end).toISOString() });
              setOpen(false);
            }}
          >
            Apply custom range
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
