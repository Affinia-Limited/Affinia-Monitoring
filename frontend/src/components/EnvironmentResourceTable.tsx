import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Columns3, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { useRefreshInterval } from "@/stores/live";
import { FilterChips } from "@/components/FilterChips";
import { HealthText } from "@/components/health";
import { LiveMark, LiveMetricInline, liveKeyMetric } from "@/components/live";
import { formatReading, keyReading } from "@/components/resourceSignals";
import { sortResources } from "@/components/ResourcesTable";
import { TimeAgo } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/menu";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useDebounce } from "@/hooks/useDebounce";
import { useLiveResources } from "@/hooks/useLiveResources";
import type { Resource } from "@/types/api";
import { cn } from "@/utils/cn";
import { regionName } from "@/utils/format";
import { paths } from "@/utils/paths";

const PAGE_SIZE = 25;
const COLUMN_STORAGE_KEY = "amp.resource-table.columns";

type HealthFilter = "all" | "healthy" | "warning" | "critical" | "unknown";
type OptionalColumn = "region" | "resource_group" | "sku" | "subscription";

const OPTIONAL_COLUMNS: { key: OptionalColumn; label: string; render: (r: Resource) => string }[] = [
  { key: "region", label: "Region", render: (r) => regionName(r.location) },
  { key: "resource_group", label: "Resource group", render: (r) => r.resource_group },
  { key: "sku", label: "SKU", render: (r) => r.sku ?? "-" },
  { key: "subscription", label: "Subscription", render: (r) => r.subscription_name ?? r.subscription_id },
];

function loadColumns(): OptionalColumn[] {
  try {
    const raw = window.localStorage.getItem(COLUMN_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((c): c is OptionalColumn => OPTIONAL_COLUMNS.some((o) => o.key === c)) : [];
  } catch {
    return [];
  }
}

function saveColumns(columns: OptionalColumn[]): void {
  try {
    window.localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(columns));
  } catch {
    // Preferences are a convenience only.
  }
}

/**
 * Resources of one environment (or project), filtered, searched and paged on the server.
 * Seven default columns; extra columns are opt-in and remembered per browser.
 */
export function EnvironmentResourceTable({
  projectId,
  environmentId,
  initialHealth = "all",
}: {
  projectId: string;
  environmentId?: string;
  initialHealth?: HealthFilter;
}) {
  const [text, setText] = useState("");
  const [health, setHealth] = useState<HealthFilter>(initialHealth);
  const [type, setType] = useState("");
  const [includeInventory, setIncludeInventory] = useState(false);
  const [page, setPage] = useState(1);
  const [columns, setColumns] = useState<OptionalColumn[]>(loadColumns);
  const q = useDebounce(text.trim(), 300);
  const scope = { project_id: projectId, environment_id: environmentId };

  const facetScope = { ...scope, monitored_only: !includeInventory };
  const facets = useQuery({ queryKey: ["facets", facetScope], queryFn: () => endpoints.facets(facetScope) });
  const filters = {
    ...scope,
    q: q || undefined,
    health: health === "all" ? undefined : health,
    resource_type: type || undefined,
    monitored_only: !includeInventory,
  };
  const refetchInterval = useRefreshInterval(60_000);
  const query = useQuery({
    queryKey: ["resources", { ...filters, page }],
    queryFn: () => endpoints.resources({ ...filters, page, page_size: PAGE_SIZE, sort: "health" }),
    placeholderData: keepPreviousData,
    refetchInterval,
  });
  const { live, byId } = useLiveResources((query.data?.items ?? []).map((r) => r.id));
  // The server orders by the last health check; while Live is on, order this page by live status.
  const items = query.data?.items ?? [];
  const rows = live ? sortResources(items, "health", (r) => byId[r.id]?.status ?? r.health_status) : items;
  const counts = Object.fromEntries((facets.data?.health ?? []).map((h) => [h.value, h.count]));
  const pages = Math.max(1, Math.ceil((query.data?.total ?? 0) / PAGE_SIZE));
  // When the total shrinks (alerts resolved, filters changed elsewhere), never strand the user on an empty page.
  useEffect(() => {
    if (query.data && page > pages) setPage(pages);
  }, [query.data, page, pages]);
  const shown = OPTIONAL_COLUMNS.filter((c) => columns.includes(c.key));
  const toggleColumn = (key: OptionalColumn) => {
    const next = columns.includes(key) ? columns.filter((c) => c !== key) : [...columns, key];
    setColumns(next);
    saveColumns(next);
  };
  const resetPage = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setPage(1);
  };

  return (
    <Card>
      <div className="space-y-3 border-b border-border p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input aria-label="Search resources" placeholder="Search resources..." className="h-8 pl-8" value={text} onChange={(e) => resetPage(setText)(e.target.value)} />
          </div>
          <Select aria-label="Resource type" className="h-8 w-52 text-xs" value={type} onChange={(e) => resetPage(setType)(e.target.value)}>
            <option value="">All resource types</option>
            {facets.data?.resource_types.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label} ({t.count})
              </option>
            ))}
          </Select>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" checked={includeInventory} onChange={(e) => resetPage(setIncludeInventory)(e.target.checked)} />
            Include inventory items
          </label>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="ml-auto h-8">
                <Columns3 /> Columns
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Optional columns</DropdownMenuLabel>
              {OPTIONAL_COLUMNS.map((c) => (
                <DropdownMenuItem
                  key={c.key}
                  role="menuitemcheckbox"
                  aria-checked={columns.includes(c.key)}
                  onSelect={(e) => {
                    e.preventDefault();
                    toggleColumn(c.key);
                  }}
                >
                  <input type="checkbox" readOnly tabIndex={-1} checked={columns.includes(c.key)} aria-hidden="true" />
                  {c.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {live ? (
          <p className="text-xs text-muted-foreground">Status filters and counts are as of the last health check; the rows show live status.</p>
        ) : null}
        <FilterChips<HealthFilter>
          label="Filter by status"
          value={health}
          onChange={resetPage(setHealth)}
          options={[
            { value: "all", label: "All" },
            { value: "critical", label: "Critical", count: counts.critical ?? 0 },
            { value: "warning", label: "Warning", count: counts.warning ?? 0 },
            { value: "healthy", label: "Healthy", count: counts.healthy ?? 0 },
            { value: "unknown", label: "Not checked", count: counts.unknown ?? 0 },
          ]}
        />
      </div>
      {query.isLoading ? (
        <TableSkeleton label="Loading resources" />
      ) : query.isError ? (
        <div className="p-4">
          <ErrorState error={query.error} title="Unable to load resources." onRetry={() => void query.refetch()} />
        </div>
      ) : (query.data?.items.length ?? 0) === 0 ? (
        q || health !== "all" || type ? (
          <EmptyState title="No resources match these filters" description="Clear the search or choose a different status." />
        ) : (
          <EmptyState title="No resources discovered" description="Resource discovery may still be running, or no Azure resources carry this environment's tag values yet." />
        )
      ) : (
        <>
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <TR>
                  <TH scope="col">Resource</TH>
                  <TH scope="col">Type</TH>
                  <TH scope="col">Status</TH>
                  <TH scope="col">Key metric</TH>
                  <TH scope="col" className="text-right">
                    Alerts
                  </TH>
                  {shown.map((c) => (
                    <TH key={c.key} scope="col">
                      {c.label}
                    </TH>
                  ))}
                  <TH scope="col">{live ? "Updated" : "Last checked"}</TH>
                  <TH scope="col" className="text-right">
                    <span className="sr-only">Action</span>
                  </TH>
                </TR>
              </THead>
              <tbody>
                {rows.map((r) => {
                  const reading = keyReading(r);
                  const state = byId[r.id];
                  const liveMetric = liveKeyMetric(state);
                  return (
                    <TR key={r.id} className="hover:bg-muted/40">
                      <TD className="max-w-72">
                        <Link to={paths.resource(r.id)} className="block truncate font-medium hover:underline" title={r.name}>
                          {r.name}
                        </Link>
                      </TD>
                      <TD className="whitespace-nowrap text-muted-foreground">{r.type_display_name}</TD>
                      <TD>
                        <HealthText status={state?.status ?? r.health_status} />
                      </TD>
                      <TD className="whitespace-nowrap">
                        {liveMetric ? (
                          <LiveMetricInline metric={liveMetric} />
                        ) : reading ? (
                          <span className={cn(reading.status === "critical" ? "text-critical" : reading.status === "warning" ? "text-warning" : "")}>
                            <span className="text-muted-foreground">{reading.label} </span>
                            <span className="tabular font-medium">{formatReading(reading)}</span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TD>
                      <TD className={cn("tabular text-right", r.active_alerts ? "font-medium text-critical" : "text-muted-foreground")}>{r.active_alerts}</TD>
                      {shown.map((c) => (
                        <TD key={c.key} className="max-w-48 truncate text-muted-foreground" title={c.render(r)}>
                          {c.render(r)}
                        </TD>
                      ))}
                      <TD className="whitespace-nowrap text-muted-foreground">
                        {state ? <LiveMark /> : <TimeAgo value={r.health_evaluated_at} />}
                      </TD>
                      <TD className="text-right">
                        <Link to={paths.resource(r.id)} className="text-sm font-medium text-primary hover:underline" aria-label={`View ${r.name}`}>
                          View
                        </Link>
                      </TD>
                    </TR>
                  );
                })}
              </tbody>
            </Table>
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-2 text-xs text-muted-foreground">
            <span aria-live="polite">
              {query.data?.total.toLocaleString("en-GB")} resource{query.data?.total === 1 ? "" : "s"}
            </span>
            <span className="flex items-center gap-1">
              <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft />
              </Button>
              Page {page} of {pages}
              <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                <ChevronRight />
              </Button>
            </span>
          </div>
        </>
      )}
    </Card>
  );
}
