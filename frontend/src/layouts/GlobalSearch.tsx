import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { HealthDot } from "@/components/status";
import { useDebounce } from "@/hooks/useDebounce";
import type { SearchHit } from "@/types/api";
import { cn } from "@/utils/cn";

const GROUPS: { kind: SearchHit["kind"]; label: string }[] = [
  { kind: "project", label: "Projects" },
  { kind: "environment", label: "Environments" },
  { kind: "resource", label: "Resources" },
  { kind: "subscription", label: "Subscriptions" },
];

export function GlobalSearch() {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const q = useDebounce(text.trim(), 250);
  const query = useQuery({ queryKey: ["search", q], queryFn: () => endpoints.search(q), enabled: q.length > 0 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const ordered = useMemo(() => {
    const hits = query.data?.hits ?? [];
    return GROUPS.flatMap((g) => hits.filter((h) => h.kind === g.kind));
  }, [query.data]);

  const go = (hit: SearchHit) => {
    navigate(hit.url);
    setOpen(false);
    setText("");
  };

  return (
    <div className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <input
        ref={inputRef}
        type="search"
        role="combobox"
        aria-expanded={open && q.length > 0}
        aria-controls="global-search-results"
        aria-label="Search projects, environments, resources and subscriptions"
        placeholder="Search resources, projects, regions..."
        className="h-9 w-full rounded-md border border-input bg-card pr-14 pl-8 text-sm placeholder:text-muted-foreground"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, ordered.length - 1));
          if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          if (e.key === "Enter" && ordered[active]) go(ordered[active]);
          if (e.key === "Escape") setOpen(false);
        }}
      />
      <kbd className="pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded border border-border px-1.5 text-[10px] text-muted-foreground sm:block">
        Ctrl K
      </kbd>
      {open && q.length > 0 ? (
        <div
          id="global-search-results"
          role="listbox"
          className="absolute top-11 z-50 max-h-96 w-full overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-lg"
        >
          {query.isLoading ? <p className="p-3 text-sm text-muted-foreground">Searching...</p> : null}
          {query.data && ordered.length === 0 ? <p className="p-3 text-sm text-muted-foreground">No matches for "{q}".</p> : null}
          {GROUPS.map((g) => {
            const hits = ordered.filter((h) => h.kind === g.kind);
            if (hits.length === 0) return null;
            return (
              <div key={g.kind} className="py-1">
                <div className="px-2 py-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{g.label}</div>
                {hits.map((hit) => {
                  const index = ordered.indexOf(hit);
                  return (
                    <button
                      key={`${hit.kind}-${hit.id}`}
                      type="button"
                      role="option"
                      aria-selected={index === active}
                      className={cn("flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted", index === active && "bg-muted")}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => go(hit)}
                    >
                      {hit.health_status ? <HealthDot status={hit.health_status} /> : null}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{hit.title}</span>
                        <span className="block truncate text-xs text-muted-foreground">{hit.subtitle}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
