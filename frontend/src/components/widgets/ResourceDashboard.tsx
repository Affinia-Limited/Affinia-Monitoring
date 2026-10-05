import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, LineChart as LineChartIcon, MoreHorizontal, Pencil, RotateCcw, Save, Trash2, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { endpoints } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/menu";
import { ErrorState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { Dashboard, ResourceDetail, Widget, WidgetIn } from "@/types/api";
import { DashboardTabs, spanClass } from "./DashboardRenderer";
import { resolveWidget } from "./registry";

export const WIDTHS = [2, 3, 4, 5, 6, 8, 12];

interface DraftWidget extends WidgetIn {
  key: string;
}

let draftCounter = 0;
const nextKey = () => `draft-${++draftCounter}`;

function toDraft(widgets: Widget[]): DraftWidget[] {
  return [...widgets]
    .sort((a, b) => a.position - b.position)
    .map((w) => ({ key: w.id, section: w.section, widget_type: w.widget_type, title: w.title, width: w.width, config: w.config }));
}

function sectionsOf(draft: DraftWidget[], fallback: string[]): string[] {
  const out = [...fallback];
  for (const w of draft) if (!out.includes(w.section)) out.push(w.section);
  return out;
}

/** Orders the payload by section so the backend's list positions keep sections contiguous. */
export function orderedPayload(draft: DraftWidget[], sections: string[]): WidgetIn[] {
  return sections.flatMap((s) =>
    draft.filter((w) => w.section === s).map(({ section, widget_type, title, width, config }) => ({ section, widget_type, title, width, config })),
  );
}

function AddChartDialog({
  resourceId,
  section,
  open,
  onOpenChange,
  onAdd,
}: {
  resourceId: string;
  section: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onAdd: (widget: DraftWidget) => void;
}) {
  const definitions = useQuery({
    queryKey: ["metric-definitions", resourceId],
    queryFn: () => endpoints.metricDefinitions(resourceId),
    enabled: open,
  });
  const [title, setTitle] = useState("");
  const [metrics, setMetrics] = useState<string[]>([]);
  const [width, setWidth] = useState(6);
  const options = (definitions.data ?? []).filter((d) => !d.split_by);
  const autoTitle = options.filter((o) => metrics.includes(o.key)).map((o) => o.label).join(", ");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Add line chart"
        description={`Added to the "${section}" section.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              disabled={metrics.length === 0}
              onClick={() => {
                onAdd({ key: nextKey(), section, widget_type: "line_chart", title: title.trim() || autoTitle, width, config: { metrics } });
                setTitle("");
                setMetrics([]);
                onOpenChange(false);
              }}
            >
              Add chart
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Title" htmlFor="add-chart-title" hint="Leave empty to use the metric names.">
            <Input id="add-chart-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <fieldset>
            <legend className="mb-1.5 text-xs font-medium">Metrics</legend>
            {definitions.isLoading ? <p className="text-sm text-muted-foreground">Loading metrics...</p> : null}
            {definitions.isError ? <ErrorState error={definitions.error} compact /> : null}
            <div className="grid max-h-64 grid-cols-1 gap-1.5 overflow-y-auto sm:grid-cols-2">
              {options.map((d) => (
                <label key={d.key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={metrics.includes(d.key)}
                    onChange={(e) => setMetrics(e.target.checked ? [...metrics, d.key] : metrics.filter((m) => m !== d.key))}
                  />
                  {d.label}
                  <span className="text-xs text-muted-foreground">({d.unit})</span>
                </label>
              ))}
            </div>
          </fieldset>
          <Field label="Width" htmlFor="add-chart-width">
            <Select id="add-chart-width" value={width} onChange={(e) => setWidth(Number(e.target.value))}>
              {WIDTHS.map((w) => (
                <option key={w} value={w}>
                  {w} of 12 columns
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function EditableWidget({
  widget,
  resource,
  first,
  last,
  onChange,
  onMove,
  onRemove,
}: {
  widget: DraftWidget;
  resource: ResourceDetail;
  first: boolean;
  last: boolean;
  onChange: (w: DraftWidget) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const Component = resolveWidget(widget.widget_type);
  const preview: Widget = { id: widget.key, position: 0, ...widget };
  const widths = WIDTHS.includes(widget.width) ? WIDTHS : [...WIDTHS, widget.width].sort((a, b) => a - b);
  return (
    <div className={spanClass(widget.width)} data-testid="editable-widget" data-title={widget.title}>
      <div className="flex h-full flex-col rounded-lg border-2 border-dashed border-primary/40">
        <div className="flex flex-wrap items-center gap-1 border-b border-border bg-muted/50 px-2 py-1">
          <span className="min-w-0 flex-1 truncate text-xs font-medium">{widget.title}</span>
          <Select
            aria-label={`Width of ${widget.title}`}
            className="h-7 w-auto min-w-20 px-2 text-xs"
            value={widget.width}
            onChange={(e) => onChange({ ...widget, width: Number(e.target.value) })}
          >
            {widths.map((w) => (
              <option key={w} value={w}>
                {w}/12
              </option>
            ))}
          </Select>
          <Button size="icon-sm" variant="ghost" aria-label={`Move ${widget.title} up`} disabled={first} onClick={() => onMove(-1)}>
            <ArrowUp />
          </Button>
          <Button size="icon-sm" variant="ghost" aria-label={`Move ${widget.title} down`} disabled={last} onClick={() => onMove(1)}>
            <ArrowDown />
          </Button>
          <Button size="icon-sm" variant="ghost" aria-label={`Remove ${widget.title}`} onClick={onRemove}>
            <Trash2 />
          </Button>
        </div>
        <div className="pointer-events-none flex-1 opacity-90" aria-hidden="true">
          <Component widget={preview} resource={resource} />
        </div>
      </div>
    </div>
  );
}

function DashboardEditor({
  dashboard,
  resource,
  onDone,
}: {
  dashboard: Dashboard;
  resource: ResourceDetail;
  onDone: (saved: Dashboard | null) => void;
}) {
  const [draft, setDraft] = useState<DraftWidget[]>(() => toDraft(dashboard.widgets));
  const sections = sectionsOf(draft, dashboard.sections);
  const [active, setActive] = useState(sections[0] ?? "Overview");
  const [adding, setAdding] = useState(false);
  const save = useMutation({
    mutationFn: () => endpoints.updateDashboard(dashboard.id, { widgets: orderedPayload(draft, sections) }),
    onSuccess: (saved) => onDone(saved),
  });

  const move = (key: string, delta: -1 | 1) => {
    setDraft((items) => {
      const w = items.find((x) => x.key === key);
      if (!w) return items;
      const same = items.filter((x) => x.section === w.section);
      const idx = same.indexOf(w);
      const swapWith = same[idx + delta];
      if (!swapWith) return items;
      const a = items.indexOf(w);
      const b = items.indexOf(swapWith);
      const next = [...items];
      [next[a], next[b]] = [next[b], next[a]];
      return next;
    });
  };

  return (
    <div className="space-y-3">
      <Card className="flex flex-wrap items-center gap-2 border-primary/40 bg-accent/40 p-3">
        <p className="mr-auto text-sm">
          <span className="font-medium">Customising this dashboard.</span>{" "}
          <span className="text-muted-foreground">Changes are saved for everyone in your organisation.</span>
        </p>
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
          <LineChartIcon /> Add line chart
        </Button>
        <Button variant="ghost" size="sm" onClick={() => onDone(null)} disabled={save.isPending}>
          <X /> Cancel
        </Button>
        <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
          <Save /> {save.isPending ? "Saving..." : "Save"}
        </Button>
      </Card>
      {save.isError ? <ErrorState error={save.error} /> : null}
      <Tabs value={active} onValueChange={setActive}>
        <TabsList aria-label="Dashboard sections">
          {sections.map((s) => (
            <TabsTrigger key={s} value={s}>
              {s}
            </TabsTrigger>
          ))}
        </TabsList>
        {sections.map((s) => {
          const items = draft.filter((w) => w.section === s);
          return (
            <TabsContent key={s} value={s}>
              {items.length === 0 ? (
                <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                  This section has no widgets. It is removed when you save.
                </p>
              ) : (
                <div className="grid grid-cols-12 gap-4">
                  {items.map((w, i) => (
                    <EditableWidget
                      key={w.key}
                      widget={w}
                      resource={resource}
                      first={i === 0}
                      last={i === items.length - 1}
                      onChange={(next) => setDraft((all) => all.map((x) => (x.key === w.key ? next : x)))}
                      onMove={(delta) => move(w.key, delta)}
                      onRemove={() => setDraft((all) => all.filter((x) => x.key !== w.key))}
                    />
                  ))}
                </div>
              )}
            </TabsContent>
          );
        })}
      </Tabs>
      <AddChartDialog
        resourceId={resource.id}
        section={active}
        open={adding}
        onOpenChange={setAdding}
        onAdd={(w) => setDraft((all) => [...all, w])}
      />
    </div>
  );
}

/** Resource dashboard with view mode (tabs) and, for dashboards:manage, a customise mode. */
export function ResourceDashboard({
  dashboard: incoming,
  resource,
  extraTabs = [],
}: {
  dashboard: Dashboard | null;
  resource: ResourceDetail;
  extraTabs?: { key: string; label: string; content: ReactNode }[];
}) {
  const qc = useQueryClient();
  const canManage = usePermission(PERMISSIONS.manageDashboards);
  const [editing, setEditing] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  // The last saved/reset version, shown immediately even before the parent query updates.
  const [latest, setLatest] = useState<Dashboard | null>(null);
  const dashboard =
    latest && incoming && latest.id === incoming.id && latest.updated_at >= incoming.updated_at ? latest : incoming;

  const store = (d: Dashboard) => {
    setLatest(d);
    qc.setQueryData(["dashboard-for", resource.id], d);
    qc.setQueryData(["dashboard", d.id], d);
  };

  if (editing && dashboard) {
    return (
      <DashboardEditor
        key={dashboard.id}
        dashboard={dashboard}
        resource={resource}
        onDone={(saved) => {
          if (saved) store(saved);
          setEditing(false);
        }}
      />
    );
  }

  const actions =
    dashboard && (canManage || dashboard.is_customized) ? (
      <>
        {dashboard.is_customized ? <span className="text-xs text-muted-foreground">Customised</span> : null}
        {canManage ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Dashboard options">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={() => setEditing(true)}>
                <Pencil /> Customise
              </DropdownMenuItem>
              {dashboard.is_customized ? (
                <DropdownMenuItem onSelect={() => setConfirmReset(true)}>
                  <RotateCcw /> Reset to template
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </>
    ) : null;

  return (
    <>
      <DashboardTabs dashboard={dashboard} resource={resource} extraTabs={extraTabs} actions={actions} />
      <Dialog open={confirmReset} onOpenChange={(o) => !resetting && setConfirmReset(o)}>
        {confirmReset && dashboard ? (
          <DialogContent
            title="Reset this dashboard to its template?"
            description="Your customisations are replaced by the current template for this resource type."
            footer={
              <>
                <Button variant="ghost" onClick={() => setConfirmReset(false)}>
                  Cancel
                </Button>
                <Button
                  disabled={resetting}
                  onClick={async () => {
                    setResetting(true);
                    try {
                      store(await endpoints.resetDashboard(dashboard.id));
                      setConfirmReset(false);
                    } finally {
                      setResetting(false);
                    }
                  }}
                >
                  Reset to template
                </Button>
              </>
            }
          >
            <p className="text-sm text-muted-foreground">This action is recorded in the audit log.</p>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}
