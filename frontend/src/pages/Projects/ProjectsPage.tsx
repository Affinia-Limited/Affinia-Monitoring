import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { PageHeader } from "@/components/common";
import { FilterChips } from "@/components/FilterChips";
import { Freshness } from "@/components/Freshness";
import { ProjectCard, ProjectCardSkeleton } from "@/components/projects/ProjectCard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/form";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { Project } from "@/types/api";
import { CreateProjectDialog } from "./ProjectForm";

type StatusFilter = "all" | "attention" | "healthy";

function effectiveStatus(p: Project): string {
  return p.health.total ? p.status : "unknown";
}

function matches(p: Project, term: string): boolean {
  if (!term) return true;
  const t = term.toLowerCase();
  return (
    p.name.toLowerCase().includes(t) ||
    p.slug.includes(t) ||
    p.description.toLowerCase().includes(t) ||
    p.environments.some((e) => e.name.toLowerCase().includes(t))
  );
}

export function ProjectsPage() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, refetchInterval: 60_000 });
  const canManage = usePermission(PERMISSIONS.manageProjects);
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const open = params.get("new") === "1";
  const setOpen = (value: boolean) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set("new", "1");
        else next.delete("new");
        return next;
      },
      { replace: true },
    );

  const all = projects.data ?? [];
  const attention = all.filter((p) => ["critical", "warning"].includes(effectiveStatus(p)) || p.active_alerts > 0);
  const visible = all
    .filter((p) => matches(p, term.trim()))
    .filter((p) =>
      status === "all" ? true : status === "attention" ? attention.includes(p) : effectiveStatus(p) === "healthy" && !p.active_alerts,
    );

  return (
    <>
      <PageHeader
        title="Projects"
        description="Each project groups its Azure resources by environment."
        actions={
          canManage ? (
            <Button onClick={() => setOpen(true)}>
              <Plus /> Add project
            </Button>
          ) : null
        }
      />
      {all.length > 0 ? (
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <div className="relative w-full max-w-sm">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input aria-label="Search projects" placeholder="Search projects..." className="pl-8" value={term} onChange={(e) => setTerm(e.target.value)} />
          </div>
          <FilterChips<StatusFilter>
            label="Filter projects by status"
            value={status}
            onChange={setStatus}
            options={[
              { value: "all", label: "All", count: all.length },
              { value: "attention", label: "Needs attention", count: attention.length },
              { value: "healthy", label: "Healthy", count: all.filter((p) => effectiveStatus(p) === "healthy" && !p.active_alerts).length },
            ]}
          />
          <Freshness updatedAt={projects.dataUpdatedAt} className="ml-auto" />
        </div>
      ) : null}
      {projects.isLoading ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3" role="status" aria-label="Loading projects">
          {[0, 1, 2, 3].map((i) => (
            <ProjectCardSkeleton key={i} />
          ))}
        </div>
      ) : projects.isError ? (
        <ErrorState error={projects.error} title="Unable to load projects." onRetry={() => void projects.refetch()} />
      ) : all.length === 0 ? (
        <Card>
          <EmptyState
            title="No projects yet"
            description="Add your first Azure project to start monitoring. Resources tagged with the project's tag values are assigned automatically."
            action={
              canManage ? (
                <Button onClick={() => setOpen(true)}>
                  <Plus /> Add project
                </Button>
              ) : null
            }
          />
        </Card>
      ) : visible.length === 0 ? (
        <Card>
          <EmptyState title="No projects match" description="Try a different search or clear the status filter." />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {visible.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}
      {canManage ? <CreateProjectDialog open={open} onOpenChange={setOpen} /> : null}
    </>
  );
}
