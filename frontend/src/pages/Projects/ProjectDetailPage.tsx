import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { Breadcrumbs } from "@/components/Breadcrumbs";
import { ConfirmButton, PageHeader } from "@/components/common";
import { Freshness } from "@/components/Freshness";
import { HEALTH_LABELS, HealthSummary, HealthText } from "@/components/health";
import { EnvironmentCard } from "@/components/projects/EnvironmentCard";
import { EnvironmentNav } from "@/components/projects/EnvironmentNav";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock, Skeleton } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { Project } from "@/types/api";
import { cn } from "@/utils/cn";
import { paths } from "@/utils/paths";
import { EnvironmentComparison } from "./EnvironmentComparison";
import { AddEnvironmentDialog } from "./ProjectForm";

function EditProjectDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [tags, setTags] = useState(project.tag_values.join(", "));
  const mutation = useMutation({
    mutationFn: () =>
      endpoints.updateProject(project.id, {
        name,
        description,
        tag_values: tags.split(",").map((t) => t.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      void qc.invalidateQueries({ queryKey: ["project", project.id] });
      onOpenChange(false);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Edit project"
        footer={
          <Button disabled={!name || mutation.isPending} onClick={() => mutation.mutate()}>
            Save changes
          </Button>
        }
      >
        <div className="space-y-3">
          <Field label="Name" htmlFor="edit-project-name">
            <Input id="edit-project-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Description" htmlFor="edit-project-description">
            <Textarea id="edit-project-description" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label="Tag values" htmlFor="edit-project-tags">
            <Input id="edit-project-tags" value={tags} onChange={(e) => setTags(e.target.value)} />
          </Field>
          {mutation.isError ? <ErrorState error={mutation.error} /> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

const COMPARISON_ROWS: { key: "total" | "healthy" | "warning" | "critical" | "unknown" | "alerts"; label: string; tone?: string }[] = [
  { key: "total", label: "Resources" },
  { key: "healthy", label: HEALTH_LABELS.healthy },
  { key: "warning", label: HEALTH_LABELS.warning, tone: "text-warning" },
  { key: "critical", label: HEALTH_LABELS.critical, tone: "text-critical" },
  { key: "unknown", label: HEALTH_LABELS.unknown },
  { key: "alerts", label: "Active alerts", tone: "text-critical" },
];

/** Environments side by side: the counts that differ stand out without reading every cell. */
function EnvironmentComparisonTable({ project }: { project: Project }) {
  return (
    <Card>
      <CardHeader title="Environment comparison" description="Monitored resources and alerts per environment" />
      <CardContent className="px-0 pb-0">
        <Table>
          <THead>
            <TR>
              <TH scope="col">Area</TH>
              {project.environments.map((e) => (
                <TH key={e.id} scope="col" className="text-right">
                  {e.name}
                </TH>
              ))}
            </TR>
          </THead>
          <tbody>
            <TR>
              <TH scope="row" className="font-normal text-muted-foreground">
                Status
              </TH>
              {project.environments.map((e) => (
                <TD key={e.id} className="text-right">
                  <HealthText status={e.health.total ? e.status : "unknown"} />
                </TD>
              ))}
            </TR>
            {COMPARISON_ROWS.map((row) => (
              <TR key={row.key}>
                <TH scope="row" className="font-normal text-muted-foreground">
                  {row.label}
                </TH>
                {project.environments.map((e) => {
                  const value = row.key === "alerts" ? e.active_alerts : e.health[row.key];
                  return (
                    <TD key={e.id} className={cn("tabular text-right font-medium", value && row.tone ? row.tone : "")}>
                      {value}
                    </TD>
                  );
                })}
              </TR>
            ))}
          </tbody>
        </Table>
      </CardContent>
    </Card>
  );
}

function ResourceTypes({ projectId }: { projectId: string }) {
  const facets = useQuery({ queryKey: ["facets", { project_id: projectId }], queryFn: () => endpoints.facets({ project_id: projectId }) });
  if (facets.isLoading) return <Skeleton className="h-40" />;
  if (facets.isError) return <ErrorState error={facets.error} compact title="Unable to load resource types." onRetry={() => void facets.refetch()} />;
  const types = facets.data?.resource_types ?? [];
  if (!types.length) return <p className="text-sm text-muted-foreground">No resources assigned yet.</p>;
  return (
    <ul className="grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
      {types.map((t) => (
        <li key={t.value} className="flex items-center justify-between gap-3">
          <span className="truncate text-muted-foreground">{t.label}</span>
          <span className="tabular font-medium">{t.count}</span>
        </li>
      ))}
    </ul>
  );
}

export function ProjectDetailPage() {
  const { projectId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const canManage = usePermission(PERMISSIONS.manageProjects);
  const [editOpen, setEditOpen] = useState(false);
  const [envOpen, setEnvOpen] = useState(false);
  const query = useQuery({ queryKey: ["project", projectId], queryFn: () => endpoints.project(projectId), refetchInterval: 60_000 });

  // Old links used ?environment=<id>; environments now have their own page.
  const legacyEnvironment = params.get("environment");
  if (legacyEnvironment && legacyEnvironment !== "comparison") return <Navigate replace to={paths.environment(projectId, legacyEnvironment)} />;

  if (query.isLoading) return <LoadingBlock label="Loading project" />;
  if (query.isError || !query.data) {
    return (
      <>
        <Breadcrumbs items={[{ label: "Projects", to: paths.projects() }, { label: "Project" }]} />
        <ErrorState error={query.error} title="Unable to load this project." onRetry={() => void query.refetch()} />
      </>
    );
  }
  const project = query.data;
  const empty = project.health.total === 0;

  return (
    <>
      <Breadcrumbs items={[{ label: "Projects", to: paths.projects() }, { label: project.name }]} />
      <PageHeader
        title={project.name}
        description={project.description || undefined}
        badge={<HealthText status={empty ? "unknown" : project.status} className="ml-1" />}
        actions={
          canManage ? (
            <>
              <Button variant="outline" size="sm" onClick={() => setEnvOpen(true)}>
                <Plus /> Environment
              </Button>
              <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                <Pencil /> Edit
              </Button>
              <ConfirmButton
                title={`Delete ${project.name}?`}
                description="The project and its environments are removed. Resources stay discovered but become unassigned."
                confirmLabel="Delete project"
                onConfirm={async () => {
                  await endpoints.deleteProject(project.id);
                  await qc.invalidateQueries({ queryKey: ["projects"] });
                  navigate(paths.projects());
                }}
              >
                <Trash2 /> Delete
              </ConfirmButton>
            </>
          ) : null
        }
      />
      <Freshness updatedAt={query.dataUpdatedAt} checkedAt={project.last_checked_at} className="-mt-4 mb-5" />
      <EnvironmentNav project={project} />

      <div className="space-y-6">
        <section aria-labelledby="project-environments">
          <h2 id="project-environments" className="mb-3 text-base font-semibold">
            Environments
          </h2>
          {project.environments.length === 0 ? (
            <Card>
              <EmptyState
                title="No environments yet"
                description="Add environments such as Development, UAT or Production. Resources are matched to them by tag values."
                action={
                  canManage ? (
                    <Button onClick={() => setEnvOpen(true)}>
                      <Plus /> Add environment
                    </Button>
                  ) : null
                }
              />
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {project.environments.map((e) => (
                <EnvironmentCard key={e.id} projectId={project.id} environment={e} />
              ))}
            </div>
          )}
        </section>

        <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
          <Card>
            <CardHeader title="Project health" description="All monitored resources in this project" />
            <CardContent className="space-y-5">
              <HealthSummary counts={project.health} title="Overall" />
              <p className="text-sm">
                <span className="text-muted-foreground">Active alerts: </span>
                <span className={cn("tabular font-medium", project.active_alerts ? "text-critical" : "")}>{project.active_alerts}</span>
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader title="Resource types" description="Everything discovered for this project, including inventory items" />
            <CardContent>
              <ResourceTypes projectId={project.id} />
            </CardContent>
          </Card>
        </div>

        {project.environments.length > 1 ? (
          <>
            <EnvironmentComparisonTable project={project} />
            <section aria-labelledby="metric-comparison">
              <h2 id="metric-comparison" className="mb-3 text-base font-semibold">
                Metric comparison
              </h2>
              <EnvironmentComparison projectId={project.id} />
            </section>
          </>
        ) : null}
      </div>

      {canManage ? (
        <>
          <EditProjectDialog key={project.id + String(editOpen)} project={project} open={editOpen} onOpenChange={setEditOpen} />
          <AddEnvironmentDialog projectId={project.id} open={envOpen} onOpenChange={setEnvOpen} />
        </>
      ) : null}
    </>
  );
}
