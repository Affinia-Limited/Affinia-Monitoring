import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { PageHeader } from "@/components/common";
import { ResourcesTable, sortResources } from "@/components/ResourcesTable";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/menu";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import { useDebounce } from "@/hooks/useDebounce";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { useFilters } from "@/stores/filters";
import type { FacetValue } from "@/types/api";
import { cn } from "@/utils/cn";
import { regionName } from "@/utils/format";
import { BulkAssignDialog } from "./BulkAssignDialog";

const PAGE_SIZE = 50;
/** Up to this many matches are sorted client-side (health first); beyond it the server pages by name. */
const CLIENT_LIMIT = 500;

const VIEWS = [
  { key: "all", label: "All" },
  { key: "attention", label: "Needs attention" },
  { key: "healthy", label: "Healthy" },
  { key: "unknown", label: "Unknown" },
  { key: "unassigned", label: "Unassigned" },
] as const;
type View = (typeof VIEWS)[number]["key"];

function viewParams(view: View): { health?: string; unassigned?: boolean } {
  if (view === "attention") return { health: "critical,warning" };
  if (view === "healthy" || view === "unknown") return { health: view };
  if (view === "unassigned") return { unassigned: true };
  return {};
}

function CompactSelect({
  label,
  value,
  options,
  onChange,
  allLabel,
  disabled,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  allLabel: string;
  disabled?: boolean;
}) {
  return (
    <Select aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} className={cn("h-9 w-auto min-w-32 max-w-52 text-sm", value && "border-primary/60")}>
      <option value="">{allLabel}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </Select>
  );
}

const facetOptions = (items: FacetValue[] | undefined, format?: (v: FacetValue) => string) =>
  (items ?? []).map((f) => ({ value: f.value, label: `${format ? format(f) : f.label} (${f.count})` }));

export function ResourcesPage() {
  const { projectId, environmentId, setProject, setEnvironment } = useFilters();
  const canManage = usePermission(PERMISSIONS.manageProjects);
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState(params.get("q") ?? "");
  const q = useDebounce(text.trim(), 300);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("health");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [assignOpen, setAssignOpen] = useState(false);

  const get = (k: string) => params.get(k) ?? "";
  const set = (changes: Record<string, string>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(changes)) {
          if (v) next.set(k, v);
          else next.delete(k);
        }
        return next;
      },
      { replace: true },
    );
  const scopeAll = get("scope") === "all";
  const view = (VIEWS.some((v) => v.key === get("view")) ? get("view") : "all") as View;

  const base = {
    project_id: projectId,
    environment_id: environmentId,
    subscription_id: get("subscription"),
    resource_group: get("rg"),
    resource_type: get("type"),
    location: get("region"),
    q,
    ...viewParams(view),
  };
  const filterKey = JSON.stringify({ base, scopeAll });
  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [filterKey]);

  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects });
  const facets = useQuery({
    queryKey: ["facets", base],
    queryFn: () => endpoints.facets(base),
    placeholderData: keepPreviousData,
  });
  const counts = useQuery({
    queryKey: ["resource-counts", base],
    queryFn: async () => {
      const [monitored, all] = await Promise.all([
        endpoints.resources({ ...base, page_size: 1, monitored_only: true }),
        endpoints.resources({ ...base, page_size: 1 }),
      ]);
      return { monitored: monitored.total, all: all.total };
    },
    placeholderData: keepPreviousData,
  });
  const list = useQuery({
    queryKey: ["resources", base, scopeAll, "client"],
    queryFn: () => endpoints.resources({ ...base, page_size: CLIENT_LIMIT, sort: "name", monitored_only: !scopeAll }),
    placeholderData: keepPreviousData,
  });
  const serverMode = (list.data?.total ?? 0) > CLIENT_LIMIT;
  const serverPage = useQuery({
    queryKey: ["resources", base, scopeAll, "server", page, sort],
    queryFn: () =>
      endpoints.resources({ ...base, page, page_size: PAGE_SIZE, sort: sort.replace("health", "name"), monitored_only: !scopeAll }),
    enabled: serverMode,
    placeholderData: keepPreviousData,
  });

  const sorted = useMemo(() => sortResources(list.data?.items ?? [], sort), [list.data, sort]);
  const total = list.data?.total ?? 0;
  const rows = serverMode ? (serverPage.data?.items ?? []) : sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // When the total shrinks (alerts resolved, filters changed elsewhere), never strand the user on an empty page.
  useEffect(() => {
    if (list.data && page > pages) setPage(pages);
  }, [list.data, page, pages]);
  const project = projects.data?.find((p) => p.id === projectId);
  const moreActive = !!(get("rg") || get("subscription"));
  const anyFilter = !!(q || get("type") || get("region") || moreActive || projectId || environmentId || view !== "all");

  return (
    <>
      <PageHeader title="Resources" description="Everything discovered in your connected subscriptions" />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="radiogroup" aria-label="Resource scope" className="inline-flex rounded-md bg-muted p-0.5 text-sm">
          {[
            { all: false, label: "Monitored", count: counts.data?.monitored },
            { all: true, label: "All", count: counts.data?.all },
          ].map((o) => (
            <button
              key={o.label}
              type="button"
              role="radio"
              aria-checked={scopeAll === o.all}
              onClick={() => set({ scope: o.all ? "all" : "" })}
              className={cn(
                "rounded px-3 py-1.5 font-medium text-muted-foreground transition-colors",
                scopeAll === o.all && "bg-card text-foreground shadow-sm",
              )}
            >
              {o.label}
              {o.count !== undefined ? <span className="tabular ml-1.5 text-muted-foreground">({o.count.toLocaleString("en-GB")})</span> : null}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5" aria-label="Quick filters">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              aria-pressed={view === v.key}
              onClick={() => set({ view: v.key === "all" ? "" : v.key })}
              className={cn(
                "rounded-full px-3 py-1 text-sm text-muted-foreground transition-colors hover:bg-muted",
                view === v.key && "bg-accent text-accent-foreground",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            aria-label="Search resources"
            className="h-9 w-full rounded-md border border-input bg-card pr-3 pl-8 text-sm placeholder:text-muted-foreground"
            placeholder="Search by name, resource group or type"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <CompactSelect label="Type" allLabel="All types" value={get("type")} options={facetOptions(facets.data?.resource_types)} onChange={(v) => set({ type: v })} />
        <CompactSelect
          label="Project"
          allLabel="All projects"
          value={projectId ?? ""}
          options={(projects.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
          onChange={(v) => setProject(v || null)}
        />
        <CompactSelect
          label="Environment"
          allLabel="All environments"
          value={environmentId ?? ""}
          disabled={!project}
          options={(project?.environments ?? []).map((e) => ({ value: e.id, label: e.name }))}
          onChange={(v) => setEnvironment(v || null)}
        />
        <CompactSelect
          label="Region"
          allLabel="All regions"
          value={get("region")}
          options={facetOptions(facets.data?.locations, (f) => regionName(f.value))}
          onChange={(v) => set({ region: v })}
        />
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" className={cn(moreActive && "border-primary/60")}>
              <SlidersHorizontal /> More filters
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-72 space-y-3">
            <Field label="Resource group" htmlFor="f-rg">
              <Select id="f-rg" value={get("rg")} onChange={(e) => set({ rg: e.target.value })}>
                <option value="">All resource groups</option>
                {facetOptions(facets.data?.resource_groups).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Subscription" htmlFor="f-sub">
              <Select id="f-sub" value={get("subscription")} onChange={(e) => set({ subscription: e.target.value })}>
                <option value="">All subscriptions</option>
                {facetOptions(facets.data?.subscriptions).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
          </PopoverContent>
        </Popover>
        {anyFilter ? (
          <Button
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => {
              setText("");
              setProject(null);
              set({ type: "", region: "", rg: "", subscription: "", view: "", q: "" });
            }}
          >
            <X /> Clear
          </Button>
        ) : null}
      </div>

      {/* serverPage loads after list reports more rows than fit client side: show loading, not an empty table. */}
      {list.isLoading || (serverMode && serverPage.isLoading) ? (
        <LoadingBlock />
      ) : list.isError ? (
        <ErrorState error={list.error} />
      ) : serverPage.isError ? (
        <ErrorState error={serverPage.error} />
      ) : (
        <Card>
          <ResourcesTable
            resources={rows}
            sort={sort}
            onSort={(s) => {
              setSort(s);
              setPage(1);
            }}
            selected={canManage ? selected : undefined}
            onSelectionChange={canManage ? setSelected : undefined}
            emptyTitle={view === "attention" ? "Nothing needs attention" : "No resources match these filters"}
          />
          <div className="flex items-center justify-between border-t border-border/70 px-5 py-2.5 text-xs text-muted-foreground">
            <span className="tabular">
              {total.toLocaleString("en-GB")} {scopeAll ? "resources" : "monitored resources"}
              {serverMode ? " · sorted by name" : ""}
            </span>
            {pages > 1 ? (
              <div className="flex items-center gap-1">
                <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  <ChevronLeft />
                </Button>
                <span className="tabular">
                  Page {page} of {pages}
                </span>
                <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                  <ChevronRight />
                </Button>
              </div>
            ) : null}
          </div>
        </Card>
      )}

      {canManage && selected.size > 0 ? (
        <div className="sticky bottom-4 z-20 mx-auto mt-4 flex w-fit items-center gap-3 rounded-lg border border-border bg-popover px-4 py-2.5 text-sm shadow-lg" role="region" aria-label="Bulk actions">
          <span className="tabular font-medium">{selected.size} selected</span>
          <Button size="sm" onClick={() => setAssignOpen(true)}>
            Assign to project...
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
        </div>
      ) : null}
      {canManage ? (
        <BulkAssignDialog ids={[...selected]} open={assignOpen} onOpenChange={setAssignOpen} onDone={() => setSelected(new Set())} />
      ) : null}
    </>
  );
}
