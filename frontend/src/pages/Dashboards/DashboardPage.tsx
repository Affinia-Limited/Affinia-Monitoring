import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { PageHeader } from "@/components/common";
import { HealthBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { ResourceDashboard } from "@/components/widgets/ResourceDashboard";

export function DashboardPage() {
  const { dashboardId = "" } = useParams();
  const dashboard = useQuery({ queryKey: ["dashboard", dashboardId], queryFn: () => endpoints.dashboard(dashboardId) });
  const resourceId = dashboard.data?.resource_id;
  const resource = useQuery({
    queryKey: ["resource", resourceId],
    queryFn: () => endpoints.resource(resourceId as string),
    enabled: !!resourceId,
  });

  if (dashboard.isLoading || resource.isLoading) return <LoadingBlock />;
  if (dashboard.isError || !dashboard.data) return <ErrorState error={dashboard.error} />;
  if (resource.isError) return <ErrorState error={resource.error} />;
  const d = dashboard.data;
  return (
    <>
      <PageHeader
        title={d.name}
        description={d.description}
        badge={d.health_status ? <HealthBadge status={d.health_status} /> : null}
        actions={
          resourceId ? (
            <Button variant="outline" size="sm" asChild>
              <Link to={`/resources/${resourceId}`}>Resource details</Link>
            </Button>
          ) : null
        }
      />
      {resource.data ? (
        <ResourceDashboard dashboard={d} resource={resource.data} />
      ) : (
        <EmptyState title="Custom dashboards without a resource are not supported yet." />
      )}
    </>
  );
}
