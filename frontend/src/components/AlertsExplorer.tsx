import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { endpoints } from "@/api/endpoints";
import { useRefreshInterval } from "@/stores/live";
import { AlertTable } from "@/components/AlertTable";
import { FilterChips } from "@/components/FilterChips";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { useDebounce } from "@/hooks/useDebounce";
import type { Alert } from "@/types/api";

const PAGE_SIZE = 50;

type StatusFilter = "open" | "active" | "acknowledged" | "resolved";
type SeverityFilter = "all" | "critical" | "warning" | "info";

const TIME_WINDOWS: { value: string; label: string }[] = [
  { value: "", label: "Any time" },
  { value: "1", label: "Last hour" },
  { value: "24", label: "Last 24 hours" },
  { value: "168", label: "Last 7 days" },
  { value: "720", label: "Last 30 days" },
];

/**
 * Alert list with server-side filtering and paging. Project and environment are either fixed by the
 * page (an environment dashboard) or chosen here (the Alerts page).
 */
export function AlertsExplorer({
  projectId,
  environmentId,
  onSelect,
  showScopeFilters = false,
  initialStatus = "open",
}: {
  projectId?: string | null;
  environmentId?: string | null;
  onSelect: (alert: Alert) => void;
  /** Show project and environment pickers (when the page has no fixed context). */
  showScopeFilters?: boolean;
  initialStatus?: StatusFilter;
}) {
  const [status, setStatus] = useState<StatusFilter>(initialStatus);
  const [severity, setSeverity] = useState<SeverityFilter>("all");
  const [text, setText] = useState("");
  const [monitorKey, setMonitorKey] = useState("");
  const [since, setSince] = useState("");
  const [scopeProject, setScopeProject] = useState(projectId ?? "");
  const [scopeEnv, setScopeEnv] = useState(environmentId ?? "");
  const [page, setPage] = useState(1);
  const q = useDebounce(text.trim(), 300);
  const effectiveProject = showScopeFilters ? scopeProject : (projectId ?? "");
  const effectiveEnv = showScopeFilters ? scopeEnv : (environmentId ?? "");

  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, enabled: showScopeFilters });
  const monitors = useQuery({ queryKey: ["monitors"], queryFn: endpoints.monitors, staleTime: 60 * 60_000 });
  const filters = {
    status,
    severity: severity === "all" ? undefined : severity,
    project_id: effectiveProject || undefined,
    environment_id: effectiveEnv || undefined,
    q: q || undefined,
    monitor_key: monitorKey || undefined,
    since_hours: since || undefined,
  };
  const refetchInterval = useRefreshInterval(60_000);
  const query = useQuery({
    queryKey: ["alerts", { ...filters, page }],
    queryFn: () => endpoints.alerts({ ...filters, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval,
  });
  const reset = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setPage(1);
  };
  const pages = Math.max(1, Math.ceil((query.data?.total ?? 0) / PAGE_SIZE));
  // When the total shrinks (alerts resolved, filters changed elsewhere), never strand the user on an empty page.
  useEffect(() => {
    if (query.data && page > pages) setPage(pages);
  }, [query.data, page, pages]);
  const selectedProject = projects.data?.find((p) => p.id === scopeProject);
  const filtered = Boolean(q || monitorKey || since || severity !== "all" || (showScopeFilters && (scopeProject || scopeEnv)));

  return (
    <Card>
      <div className="space-y-3 border-b border-border p-3">
        <div className="flex flex-wrap items-center gap-3">
          <FilterChips<StatusFilter>
            label="Alert status"
            value={status}
            onChange={reset(setStatus)}
            options={[
              { value: "open", label: "Open" },
              { value: "active", label: "Active" },
              { value: "acknowledged", label: "Acknowledged" },
              { value: "resolved", label: "Resolved" },
            ]}
          />
          <span className="hidden h-5 w-px bg-border sm:block" aria-hidden="true" />
          <FilterChips<SeverityFilter>
            label="Severity"
            value={severity}
            onChange={reset(setSeverity)}
            options={[
              { value: "all", label: "All severities" },
              { value: "critical", label: "Critical" },
              { value: "warning", label: "Warning" },
              { value: "info", label: "Info" },
            ]}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input aria-label="Search alerts" placeholder="Search alerts or resources..." className="h-8 pl-8" value={text} onChange={(e) => reset(setText)(e.target.value)} />
          </div>
          {showScopeFilters ? (
            <>
              <Select
                aria-label="Project"
                className="h-8 w-44 text-xs"
                value={scopeProject}
                onChange={(e) => {
                  setScopeProject(e.target.value);
                  setScopeEnv("");
                  setPage(1);
                }}
              >
                <option value="">All projects</option>
                {projects.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
              <Select aria-label="Environment" className="h-8 w-44 text-xs" value={scopeEnv} disabled={!selectedProject} onChange={(e) => reset(setScopeEnv)(e.target.value)}>
                <option value="">All environments</option>
                {selectedProject?.environments.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name}
                  </option>
                ))}
              </Select>
            </>
          ) : null}
          <Select aria-label="Resource type" className="h-8 w-48 text-xs" value={monitorKey} onChange={(e) => reset(setMonitorKey)(e.target.value)}>
            <option value="">All resource types</option>
            {monitors.data
              ?.filter((m) => m.key !== "generic")
              .map((m) => (
                <option key={m.key} value={m.key}>
                  {m.display_name}
                </option>
              ))}
          </Select>
          <Select aria-label="Time" className="h-8 w-36 text-xs" value={since} onChange={(e) => reset(setSince)(e.target.value)}>
            {TIME_WINDOWS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
          <span className="ml-auto text-xs text-muted-foreground" aria-live="polite">
            {query.data ? `${query.data.total.toLocaleString("en-GB")} alert${query.data.total === 1 ? "" : "s"}` : null}
          </span>
        </div>
      </div>
      {query.isLoading ? (
        <TableSkeleton label="Loading alerts" />
      ) : query.isError ? (
        <div className="p-4">
          <ErrorState error={query.error} title="Unable to load alerts." onRetry={() => void query.refetch()} />
        </div>
      ) : (query.data?.items.length ?? 0) === 0 ? (
        filtered || status === "resolved" ? (
          <EmptyState title="No alerts match these filters" description="Try a wider time window or clear the filters." />
        ) : (
          <EmptyState
            icon={<CheckCircle2 className="size-8 text-healthy" />}
            title="No active alerts"
            description="Everything is currently within its alert thresholds."
          />
        )
      ) : (
        <>
          <AlertTable alerts={query.data?.items ?? []} onSelect={onSelect} compact={!showScopeFilters} />
          {pages > 1 ? (
            <div className="flex items-center justify-end gap-1 border-t border-border px-4 py-2 text-xs text-muted-foreground">
              <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft />
              </Button>
              Page {page} of {pages}
              <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                <ChevronRight />
              </Button>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}
