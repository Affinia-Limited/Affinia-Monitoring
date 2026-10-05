import { useQuery } from "@tanstack/react-query";
import { LayoutGrid } from "lucide-react";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { PageHeader } from "@/components/common";
import { HealthDot } from "@/components/status";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { useFilters } from "@/stores/filters";
import type { DashboardSummary } from "@/types/api";

export function DashboardsPage() {
  const { projectId, environmentId } = useFilters();
  const query = useQuery({
    queryKey: ["dashboards", projectId, environmentId],
    queryFn: () => endpoints.dashboards({ project_id: projectId, environment_id: environmentId }),
  });
  const groups = new Map<string, DashboardSummary[]>();
  for (const d of query.data ?? []) {
    const key = d.type_display_name ?? "Custom";
    groups.set(key, [...(groups.get(key) ?? []), d]);
  }
  return (
    <>
      <PageHeader title="Dashboards" description="Generated automatically from each resource type's template" />
      {query.isLoading ? (
        <LoadingBlock />
      ) : query.isError ? (
        <ErrorState error={query.error} />
      ) : groups.size === 0 ? (
        <Card>
          <EmptyState icon={<LayoutGrid className="size-8" />} title="No dashboards yet" description="Dashboards are created after resources are discovered." />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {[...groups.entries()]
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([type, items]) => (
              <Card key={type}>
                <CardHeader title={type} description={`${items.length} dashboard${items.length === 1 ? "" : "s"}`} />
                <CardContent>
                  <ul className="divide-y divide-border">
                    {items.map((d) => (
                      <li key={d.id}>
                        <Link to={d.resource_id ? `/resources/${d.resource_id}` : `/dashboards/${d.id}`} className="flex items-center gap-2 py-2 text-sm hover:underline">
                          <HealthDot status={d.health_status} />
                          <span className="min-w-0 flex-1 truncate font-medium">{d.name}</span>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {[d.project_name, d.environment_name].filter(Boolean).join(" / ") || "Unassigned"}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ))}
        </div>
      )}
    </>
  );
}
