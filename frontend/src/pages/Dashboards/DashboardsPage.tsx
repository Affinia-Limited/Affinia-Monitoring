import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Folder, FolderOpen, LayoutGrid, List, Search, Star, Tag, X } from "lucide-react";
import { type CSSProperties, type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { PageHeader } from "@/components/common";
import { HealthDot } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/menu";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { useFilters } from "@/stores/filters";
import type { DashboardSummary } from "@/types/api";
import { cn } from "@/utils/cn";

const STAR_KEY = "amp.dashboards.starred";
const UNASSIGNED = "Unassigned";
const NO_ENVIRONMENT = "No environment";
const HEALTH_RANK: Record<string, number> = { critical: 0, warning: 1, unknown: 2, healthy: 3 };

type View = "folders" | "list";
type Sort = "name" | "-name" | "updated" | "health";

function loadStars(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STAR_KEY) ?? "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : []);
  } catch {
    return new Set();
  }
}

function saveStars(stars: Set<string>): void {
  try {
    window.localStorage.setItem(STAR_KEY, JSON.stringify([...stars]));
  } catch {
    // Starring is a per-browser convenience only.
  }
}

/** Stable colour per tag from the chart palette (works in light and dark mode). */
function tagStyle(tag: string): CSSProperties {
  let hash = 0;
  for (const ch of tag) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  const v = `var(--chart-${(hash % 8) + 1})`;
  return { color: v, background: `color-mix(in srgb, ${v} 16%, transparent)`, borderColor: `color-mix(in srgb, ${v} 35%, transparent)` };
}

export function TagChip({ tag, onClick, active }: { tag: string; onClick?: () => void; active?: boolean }) {
  const className = cn("inline-flex h-6 items-center rounded border px-1.5 text-xs font-medium whitespace-nowrap", active && "ring-1 ring-current");
  return onClick ? (
    <button type="button" className={cn(className, "hover:opacity-80")} style={tagStyle(tag)} onClick={onClick} aria-pressed={active} title={`Filter by ${tag}`}>
      {tag}
    </button>
  ) : (
    <span className={className} style={tagStyle(tag)}>
      {tag}
    </span>
  );
}

function sortDashboards(items: DashboardSummary[], sort: Sort): DashboardSummary[] {
  const byName = (a: DashboardSummary, b: DashboardSummary) => a.name.localeCompare(b.name);
  const compare: Record<Sort, (a: DashboardSummary, b: DashboardSummary) => number> = {
    name: byName,
    "-name": (a, b) => -byName(a, b),
    updated: (a, b) => b.updated_at.localeCompare(a.updated_at) || byName(a, b),
    health: (a, b) => (HEALTH_RANK[a.health_status ?? "unknown"] ?? 9) - (HEALTH_RANK[b.health_status ?? "unknown"] ?? 9) || byName(a, b),
  };
  return [...items].sort(compare[sort]);
}

interface EnvGroup {
  name: string;
  order: number;
  items: DashboardSummary[];
}

interface ProjectGroup {
  name: string;
  envs: EnvGroup[];
  count: number;
}

/** Project folders, each with environment subfolders in the project's own order; Unassigned last. */
function groupByProject(items: DashboardSummary[]): ProjectGroup[] {
  const projects = new Map<string, Map<string, EnvGroup>>();
  for (const d of items) {
    const project = d.project_name ?? UNASSIGNED;
    const env = d.environment_name ?? NO_ENVIRONMENT;
    const envs = projects.get(project) ?? new Map<string, EnvGroup>();
    const group = envs.get(env) ?? { name: env, order: d.environment_order ?? 9999, items: [] };
    group.items.push(d);
    envs.set(env, group);
    projects.set(project, envs);
  }
  return [...projects.entries()]
    .map(([name, envs]) => {
      const list = [...envs.values()].sort((a, b) => a.order - b.order || a.name.localeCompare(b.name));
      return { name, envs: list, count: list.reduce((n, e) => n + e.items.length, 0) };
    })
    .sort((a, b) => (a.name === UNASSIGNED ? 1 : b.name === UNASSIGNED ? -1 : a.name.localeCompare(b.name)));
}

function DashboardRow({
  d,
  depth,
  starred,
  onStar,
  onTag,
  activeTags,
  showLocation,
}: {
  d: DashboardSummary;
  depth: number;
  starred: boolean;
  onStar: () => void;
  onTag: (tag: string) => void;
  activeTags: Set<string>;
  showLocation?: boolean;
}) {
  return (
    <div role="row" className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b border-border/60 px-4 py-2 hover:bg-muted/40 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div role="cell" className="flex min-w-0 items-center gap-2" style={{ paddingLeft: depth * 24 }}>
        <LayoutGrid className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <Link to={d.resource_id ? `/resources/${d.resource_id}` : `/dashboards/${d.id}`} className="truncate text-sm font-medium hover:underline">
          {d.name}
        </Link>
        <HealthDot status={d.health_status} className="size-2" />
        {showLocation ? (
          <span className="hidden truncate text-xs text-muted-foreground sm:inline">
            {[d.project_name ?? UNASSIGNED, d.environment_name].filter(Boolean).join(" / ")}
          </span>
        ) : null}
        <button
          type="button"
          onClick={onStar}
          aria-pressed={starred}
          aria-label={starred ? `Unstar ${d.name}` : `Star ${d.name}`}
          className="ml-auto rounded p-1 text-muted-foreground hover:text-foreground"
        >
          <Star className={cn("size-4", starred && "fill-warning text-warning")} />
        </button>
      </div>
      <div role="cell" className="hidden flex-wrap gap-1.5 md:flex">
        {d.tags.map((t) => (
          <TagChip key={t} tag={t} onClick={() => onTag(t)} active={activeTags.has(t)} />
        ))}
      </div>
    </div>
  );
}

function FolderRow({
  name,
  count,
  depth,
  open,
  onToggle,
}: {
  name: string;
  count: number;
  depth: number;
  open: boolean;
  onToggle: () => void;
}) {
  const Icon = open ? FolderOpen : Folder;
  return (
    <div role="row" className="border-b border-border/60 hover:bg-muted/40">
      <div role="cell">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm font-medium"
        style={{ paddingLeft: 16 + depth * 24 }}
      >
        {open ? <ChevronDown className="size-4 text-muted-foreground" /> : <ChevronRight className="size-4 text-muted-foreground" />}
        <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
        {name}
        <span className="text-xs font-normal text-muted-foreground">{count}</span>
      </button>
      </div>
    </div>
  );
}

function TagFilter({ tags, selected, onChange }: { tags: [string, number][]; selected: Set<string>; onChange: (next: Set<string>) => void }) {
  const [text, setText] = useState("");
  const visible = tags.filter(([t]) => t.includes(text.trim().toLowerCase()));
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" className="h-9 min-w-44 justify-start gap-2">
          <Tag className="size-4" />
          {selected.size ? `${selected.size} tag${selected.size === 1 ? "" : "s"}` : "Filter by tag"}
          <ChevronDown className="ml-auto size-4 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-2">
        <Input aria-label="Find a tag" placeholder="Find a tag..." className="mb-2 h-8" value={text} onChange={(e) => setText(e.target.value)} />
        <ul className="max-h-64 space-y-0.5 overflow-y-auto" aria-label="Tags">
          {visible.map(([tag, count]) => (
            <li key={tag}>
              <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted">
                <input
                  type="checkbox"
                  checked={selected.has(tag)}
                  onChange={() => {
                    const next = new Set(selected);
                    if (next.has(tag)) next.delete(tag);
                    else next.add(tag);
                    onChange(next);
                  }}
                />
                <TagChip tag={tag} />
                <span className="ml-auto text-xs text-muted-foreground">{count}</span>
              </label>
            </li>
          ))}
          {visible.length === 0 ? <li className="px-1.5 py-1 text-xs text-muted-foreground">No matching tags.</li> : null}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

export function DashboardsPage() {
  const { projectId, environmentId } = useFilters();
  const query = useQuery({
    queryKey: ["dashboards", projectId, environmentId],
    queryFn: () => endpoints.dashboards({ project_id: projectId, environment_id: environmentId }),
  });
  const [text, setText] = useState("");
  const [tags, setTags] = useState<Set<string>>(new Set());
  const [starredOnly, setStarredOnly] = useState(false);
  const [view, setView] = useState<View>("folders");
  const [sort, setSort] = useState<Sort>("name");
  const [stars, setStars] = useState<Set<string>>(loadStars);
  // Folder open state; folders are open unless the user closed them ("Unassigned" starts closed).
  const [closed, setClosed] = useState<Set<string>>(() => new Set([UNASSIGNED]));

  const all = useMemo(() => query.data ?? [], [query.data]);
  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    all.forEach((d) => d.tags.forEach((t) => counts.set(t, (counts.get(t) ?? 0) + 1)));
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [all]);

  const term = text.trim().toLowerCase();
  const filtered = all.filter(
    (d) =>
      (!term ||
        d.name.toLowerCase().includes(term) ||
        (d.project_name ?? "").toLowerCase().includes(term) ||
        (d.environment_name ?? "").toLowerCase().includes(term) ||
        (d.type_display_name ?? "").toLowerCase().includes(term)) &&
      [...tags].every((t) => d.tags.includes(t)) &&
      (!starredOnly || stars.has(d.id)),
  );
  const narrowed = Boolean(term || tags.size || starredOnly);
  const sorted = sortDashboards(filtered, sort);

  const toggleStar = (id: string) => {
    const next = new Set(stars);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setStars(next);
    saveStars(next);
  };
  const toggleTag = (tag: string) => {
    const next = new Set(tags);
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    setTags(next);
  };
  const toggleFolder = (key: string) => {
    const next = new Set(closed);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setClosed(next);
  };
  // While searching or filtering, every folder with a match is shown open.
  const isOpen = (key: string) => narrowed || !closed.has(key);
  const row = (d: DashboardSummary, depth: number, showLocation = false) => (
    <DashboardRow
      key={d.id}
      d={d}
      depth={depth}
      starred={stars.has(d.id)}
      onStar={() => toggleStar(d.id)}
      onTag={toggleTag}
      activeTags={tags}
      showLocation={showLocation}
    />
  );

  let body: ReactNode;
  if (view === "list") {
    body = sorted.map((d) => row(d, 0, true));
  } else {
    body = groupByProject(sorted).map((project) => {
      const projectKey = project.name;
      const singleEnvUnassigned = project.envs.length === 1 && project.envs[0].name === NO_ENVIRONMENT;
      return (
        <div key={projectKey} role="rowgroup">
          <FolderRow name={project.name} count={project.count} depth={0} open={isOpen(projectKey)} onToggle={() => toggleFolder(projectKey)} />
          {isOpen(projectKey)
            ? singleEnvUnassigned
              ? project.envs[0].items.map((d) => row(d, 1))
              : project.envs.map((env) => {
                  const envKey = `${projectKey}/${env.name}`;
                  return (
                    <div key={envKey} role="rowgroup">
                      <FolderRow name={env.name} count={env.items.length} depth={1} open={isOpen(envKey)} onToggle={() => toggleFolder(envKey)} />
                      {isOpen(envKey) ? env.items.map((d) => row(d, 2)) : null}
                    </div>
                  );
                })
            : null}
        </div>
      );
    });
  }

  return (
    <>
      <PageHeader title="Dashboards" description="Every monitored resource gets a dashboard built from its type's template, organised by project and environment." />
      <div className="mb-3 relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input aria-label="Search dashboards" placeholder="Search dashboards, projects and environments" className="h-10 pl-9" value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <TagFilter tags={tagCounts} selected={tags} onChange={setTags} />
        <label className="inline-flex items-center gap-2 text-sm">
          <input type="checkbox" checked={starredOnly} onChange={(e) => setStarredOnly(e.target.checked)} />
          Starred
        </label>
        {tags.size ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {[...tags].map((t) => (
              <TagChip key={t} tag={t} onClick={() => toggleTag(t)} active />
            ))}
            <Button variant="ghost" size="sm" onClick={() => setTags(new Set())}>
              <X /> Clear
            </Button>
          </div>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <div role="group" aria-label="View" className="inline-flex rounded-md border border-border p-0.5">
            <Button variant={view === "folders" ? "secondary" : "ghost"} size="icon-sm" aria-label="Folder view" aria-pressed={view === "folders"} onClick={() => setView("folders")}>
              <Folder />
            </Button>
            <Button variant={view === "list" ? "secondary" : "ghost"} size="icon-sm" aria-label="List view" aria-pressed={view === "list"} onClick={() => setView("list")}>
              <List />
            </Button>
          </div>
          <Select aria-label="Sort" className="h-9 w-44" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="name">Sort: A to Z</option>
            <option value="-name">Sort: Z to A</option>
            <option value="updated">Sort: Recently updated</option>
            <option value="health">Sort: Needs attention</option>
          </Select>
        </div>
      </div>
      <Card className="overflow-hidden">
        <div role="table" aria-label="Dashboards">
          <div role="row" className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 border-b border-border bg-muted/50 px-4 py-2 text-sm font-medium md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <span role="columnheader">Name</span>
            <span role="columnheader" className="hidden md:block">
              Tags
            </span>
          </div>
          {query.isLoading ? (
            <TableSkeleton label="Loading dashboards" />
          ) : query.isError ? (
            <div className="p-4">
              <ErrorState error={query.error} title="Unable to load dashboards." onRetry={() => void query.refetch()} />
            </div>
          ) : all.length === 0 ? (
            <EmptyState icon={<LayoutGrid className="size-8" />} title="No dashboards yet" description="Dashboards are created automatically after resources are discovered." />
          ) : sorted.length === 0 ? (
            <EmptyState title="No dashboards match" description="Try a different search, or clear the tag and starred filters." />
          ) : (
            body
          )}
        </div>
      </Card>
      <p className="mt-2 text-xs text-muted-foreground">
        {sorted.length.toLocaleString("en-GB")} of {all.length.toLocaleString("en-GB")} dashboards. Stars are saved in this browser.
      </p>
    </>
  );
}
