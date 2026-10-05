import { ArrowDown, ArrowUp } from "lucide-react";
import { Link } from "react-router-dom";
import type { Resource } from "@/types/api";
import { regionName } from "@/utils/format";
import { HealthDot } from "./status";
import { EmptyState } from "./ui/states";
import { LG_ONLY, Table, TD, TH, THead, TR } from "./ui/table";

export type ResourceSort = "health" | "name" | "type" | "location";

const HEALTH_ORDER: Record<string, number> = { critical: 0, warning: 1, unknown: 2, healthy: 3 };

/** Health first (critical, warning, unknown, healthy), then name. Prefix "-" to reverse. */
export function sortResources(items: Resource[], sort: string): Resource[] {
  const desc = sort.startsWith("-");
  const key = sort.replace("-", "") as ResourceSort;
  const byName = (a: Resource, b: Resource) => a.name.localeCompare(b.name);
  const compare = (a: Resource, b: Resource): number => {
    switch (key) {
      case "health":
        return (HEALTH_ORDER[a.health_status] ?? 9) - (HEALTH_ORDER[b.health_status] ?? 9) || byName(a, b);
      case "type":
        return a.type_display_name.localeCompare(b.type_display_name) || byName(a, b);
      case "location":
        return (a.location ?? "").localeCompare(b.location ?? "") || byName(a, b);
      default:
        return byName(a, b);
    }
  };
  return [...items].sort((a, b) => (desc ? -compare(a, b) : compare(a, b)));
}

function SortHeader({
  label,
  column,
  sort,
  onSort,
  className,
}: {
  label: string;
  column: ResourceSort;
  sort?: string;
  onSort?: (sort: string) => void;
  className?: string;
}) {
  if (!onSort) return <TH className={className}>{label}</TH>;
  const active = sort?.replace("-", "") === column;
  const desc = sort?.startsWith("-");
  return (
    <TH className={className} aria-sort={active ? (desc ? "descending" : "ascending") : "none"}>
      <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => onSort(active && !desc ? `-${column}` : column)}>
        {label}
        {active ? desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" /> : null}
      </button>
    </TH>
  );
}

export function ResourcesTable({
  resources,
  sort,
  onSort,
  showProject = true,
  selected,
  onSelectionChange,
  emptyTitle = "No resources match these filters",
}: {
  resources: Resource[];
  sort?: string;
  onSort?: (sort: string) => void;
  showProject?: boolean;
  /** Enables row checkboxes when provided. */
  selected?: Set<string>;
  onSelectionChange?: (next: Set<string>) => void;
  emptyTitle?: string;
}) {
  if (resources.length === 0) {
    return <EmptyState title={emptyTitle} description="Clear the filters, or run a synchronisation from Azure Connections." />;
  }
  const selectable = !!selected && !!onSelectionChange;
  const allSelected = selectable && resources.every((r) => selected.has(r.id));
  const someSelected = selectable && !allSelected && resources.some((r) => selected.has(r.id));
  const toggleAll = () => {
    if (!selectable) return;
    const next = new Set(selected);
    resources.forEach((r) => (allSelected ? next.delete(r.id) : next.add(r.id)));
    onSelectionChange(next);
  };
  return (
    <Table>
      <THead>
        <TR>
          {selectable ? (
            <TH className="w-10">
              <input
                type="checkbox"
                aria-label="Select all resources on this page"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = someSelected;
                }}
                onChange={toggleAll}
              />
            </TH>
          ) : null}
          <SortHeader label="Name" column="name" sort={sort} onSort={onSort} />
          <SortHeader label="Type" column="type" sort={sort} onSort={onSort} />
          {showProject ? <TH>Project / Environment</TH> : null}
          <SortHeader label="Region" column="location" sort={sort} onSort={onSort} />
          <TH className={LG_ONLY}>Resource group</TH>
        </TR>
      </THead>
      <tbody>
        {resources.map((r) => (
          <TR key={r.id} className="hover:bg-muted/40" data-selected={selected?.has(r.id) || undefined}>
            {selectable ? (
              <TD className="w-10">
                <input
                  type="checkbox"
                  aria-label={`Select ${r.name}`}
                  checked={selected.has(r.id)}
                  onChange={() => {
                    const next = new Set(selected);
                    if (next.has(r.id)) next.delete(r.id);
                    else next.add(r.id);
                    onSelectionChange(next);
                  }}
                />
              </TD>
            ) : null}
            <TD>
              <span className="flex min-w-0 items-center gap-2.5">
                <HealthDot status={r.health_status} />
                <Link to={`/resources/${r.id}`} className="truncate font-medium hover:underline">
                  {r.name}
                </Link>
              </span>
            </TD>
            <TD className="whitespace-nowrap text-muted-foreground">{r.type_display_name}</TD>
            {showProject ? (
              <TD className="whitespace-nowrap">
                {r.project_name ? (
                  <>
                    {r.project_name}
                    <span className="text-muted-foreground"> / {r.environment_name ?? "-"}</span>
                  </>
                ) : (
                  <span className="text-muted-foreground">Unassigned</span>
                )}
              </TD>
            ) : null}
            <TD className="whitespace-nowrap text-muted-foreground">{regionName(r.location)}</TD>
            <TD className={`max-w-56 truncate text-muted-foreground ${LG_ONLY}`} title={r.resource_group}>
              {r.resource_group}
            </TD>
          </TR>
        ))}
      </tbody>
    </Table>
  );
}
