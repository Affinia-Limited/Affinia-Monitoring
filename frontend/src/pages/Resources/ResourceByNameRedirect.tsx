import { useQuery } from "@tanstack/react-query";
import { Navigate, useParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";

/** /app-services/:name -> /resources/:id, resolved by exact name among App Services. */
export function ResourceByNameRedirect() {
  const { name = "" } = useParams();
  const query = useQuery({
    queryKey: ["resource-by-name", name],
    queryFn: () => endpoints.resources({ q: name, page_size: 50 }),
  });
  if (query.isLoading) return <LoadingBlock />;
  if (query.isError) return <ErrorState error={query.error} />;
  const items = query.data?.items ?? [];
  const match =
    items.find((r) => r.name.toLowerCase() === name.toLowerCase() && r.resource_type === "microsoft.web/sites") ??
    items.find((r) => r.name.toLowerCase() === name.toLowerCase());
  if (!match) return <EmptyState title={`No resource named "${name}" was found.`} />;
  return <Navigate to={`/resources/${match.id}`} replace />;
}
