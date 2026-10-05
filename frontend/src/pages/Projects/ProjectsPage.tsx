import { useQuery } from "@tanstack/react-query";
import { Bell, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { PageHeader } from "@/components/common";
import { HealthBadge, HealthDot } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { CreateProjectDialog } from "./ProjectForm";

export function ProjectsPage() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects });
  const canManage = usePermission(PERMISSIONS.manageProjects);
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Projects"
        description="Applications grouped by environment"
        actions={
          canManage ? (
            <Button onClick={() => setOpen(true)}>
              <Plus /> New project
            </Button>
          ) : null
        }
      />
      {projects.isLoading ? (
        <LoadingBlock />
      ) : projects.isError ? (
        <ErrorState error={projects.error} />
      ) : (projects.data ?? []).length === 0 ? (
        <Card>
          <EmptyState title="No projects yet" description="Create a project, then connect Azure. Resources tagged with the project name are assigned automatically." />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.data?.map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="group">
              <Card className="h-full p-4 transition-colors group-hover:border-primary/50">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold">{p.name}</h2>
                    <p className="line-clamp-2 text-sm text-muted-foreground">{p.description || p.slug}</p>
                  </div>
                  <HealthBadge status={p.status} />
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {p.environments.map((e) => (
                    <span key={e.id} className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs">
                      <HealthDot status={e.status} />
                      {e.name}
                      <span className="text-muted-foreground">{e.health.total}</span>
                    </span>
                  ))}
                  {p.environments.length === 0 ? <span className="text-xs text-muted-foreground">No environments</span> : null}
                </div>
                <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                  <span>{p.health.total} resources</span>
                  <span className="inline-flex items-center gap-1">
                    <Bell className="size-3.5" />
                    {p.active_alerts} open alerts
                  </span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
      {canManage ? <CreateProjectDialog open={open} onOpenChange={setOpen} /> : null}
    </>
  );
}
