import type { ReactNode } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Dashboard, ResourceDetail, Widget } from "@/types/api";
import { cn } from "@/utils/cn";
import { resolveWidget } from "./registry";

// Static class names so Tailwind can see them.
const SPAN: Record<number, string> = {
  1: "lg:col-span-1",
  2: "lg:col-span-2",
  3: "lg:col-span-3",
  4: "lg:col-span-4",
  5: "lg:col-span-5",
  6: "lg:col-span-6",
  7: "lg:col-span-7",
  8: "lg:col-span-8",
  9: "lg:col-span-9",
  10: "lg:col-span-10",
  11: "lg:col-span-11",
  12: "lg:col-span-12",
};

export function spanClass(width: number): string {
  const w = Math.min(12, Math.max(1, Math.round(width)));
  return cn("col-span-12", w <= 6 ? "md:col-span-6" : "md:col-span-12", w <= 3 && "sm:col-span-6", SPAN[w]);
}

/** Renders any widget list on a 12-column responsive grid. Used by every dashboard in the app. */
export function DashboardRenderer({ widgets, resource }: { widgets: Widget[]; resource: ResourceDetail }) {
  const ordered = [...widgets].sort((a, b) => a.position - b.position);
  return (
    <div className="grid grid-cols-12 gap-4" data-testid="dashboard-grid">
      {ordered.map((widget) => {
        const Component = resolveWidget(widget.widget_type);
        return (
          <div key={widget.id} className={spanClass(widget.width)} data-widget-type={widget.widget_type}>
            <Component widget={widget} resource={resource} />
          </div>
        );
      })}
    </div>
  );
}

/** Dashboard sections as tabs, with optional extra fixed tabs appended (e.g. Health, Tags). */
export function DashboardTabs({
  dashboard,
  resource,
  extraTabs = [],
  actions,
}: {
  dashboard: Dashboard | null;
  resource: ResourceDetail;
  extraTabs?: { key: string; label: string; content: ReactNode }[];
  /** Rendered at the right-hand end of the tab bar (e.g. an overflow menu). */
  actions?: ReactNode;
}) {
  const sections = dashboard?.sections ?? [];
  const first = sections[0] ?? extraTabs[0]?.key ?? "overview";
  return (
    <Tabs defaultValue={first}>
      <div className="flex items-end gap-2 border-b border-border">
      <TabsList aria-label="Dashboard sections" className="min-w-0 flex-1 border-b-0">
        {sections.map((s) => (
          <TabsTrigger key={s} value={s}>
            {s}
          </TabsTrigger>
        ))}
        {extraTabs.map((t) => (
          <TabsTrigger key={t.key} value={t.key}>
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {actions ? <div className="flex shrink-0 items-center gap-2 pb-1.5">{actions}</div> : null}
      </div>
      {sections.map((s) => (
        <TabsContent key={s} value={s} className="pt-6">
          <DashboardRenderer widgets={dashboard?.widgets.filter((w) => w.section === s) ?? []} resource={resource} />
        </TabsContent>
      ))}
      {extraTabs.map((t) => (
        <TabsContent key={t.key} value={t.key}>
          {t.content}
        </TabsContent>
      ))}
    </Tabs>
  );
}
