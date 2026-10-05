import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { ConfirmButton, KpiCard, PageHeader } from "@/components/common";
import { ResourcesTable, sortResources } from "@/components/ResourcesTable";
import { HealthBadge, HealthDot } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { Project } from "@/types/api";
import { EnvironmentComparison } from "./EnvironmentComparison";
import { AddEnvironmentDialog } from "./ProjectForm";

function EnvironmentResources({ projectId, environmentId }: { projectId: string; environmentId?: string }) {
  const query = useQuery({
    queryKey: ["resources", { project_id: projectId, environment_id: environmentId, page_size: 200 }],
    queryFn: () => endpoints.resources({ project_id: projectId, environment_id: environmentId, page_size: 200, monitored_only: true }),
  });
  if (query.isLoading) return <LoadingBlock />;
  if (query.isError) return <ErrorState error={query.error} />;
  return (
    <Card>
      <ResourcesTable resources={sortResources(query.data?.items ?? [], "health")} showProject={false} />
    </Card>
  );
}

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

export function ProjectDetailPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const canManage = usePermission(PERMISSIONS.manageProjects);
  const [editOpen, setEditOpen] = useState(false);
  const [envOpen, setEnvOpen] = useState(false);
  const query = useQuery({ queryKey: ["project", projectId], queryFn: () => endpoints.project(projectId) });

  if (query.isLoading) return <LoadingBlock />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const project = query.data;
  const tab = params.get("environment") ?? project.environments[0]?.id ?? "comparison";

  return (
    <>
      <PageHeader
        title={project.name}
        description={project.description || `Project ${project.slug}`}
        badge={<HealthBadge status={project.status} />}
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
                  navigate("/projects");
                }}
              >
                <Trash2 /> Delete
              </ConfirmButton>
            </>
          ) : null
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <KpiCard label="Resources" value={project.health.total} />
        <KpiCard label="Healthy" value={project.health.healthy} tone="healthy" />
        <KpiCard label="Warning" value={project.health.warning} tone="warning" />
        <KpiCard label="Critical" value={project.health.critical} tone="critical" />
        <KpiCard label="Open alerts" value={project.active_alerts} tone={project.active_alerts ? "critical" : undefined} />
      </div>
      <Tabs
        value={tab}
        onValueChange={(v) =>
          setParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.set("environment", v);
              return next;
            },
            { replace: true },
          )
        }
      >
        <TabsList aria-label="Environments">
          {project.environments.map((e) => (
            <TabsTrigger key={e.id} value={e.id}>
              <span className="inline-flex items-center gap-2">
                <HealthDot status={e.status} />
                {e.name}
                <span className="text-xs text-muted-foreground">{e.health.total}</span>
              </span>
            </TabsTrigger>
          ))}
          <TabsTrigger value="comparison">Environment comparison</TabsTrigger>
        </TabsList>
        {project.environments.map((e) => (
          <TabsContent key={e.id} value={e.id}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
              <span>
                Tag values: {e.tag_values.length ? e.tag_values.join(", ") : "none"} ({e.kind})
              </span>
              {canManage ? (
                <ConfirmButton
                  title={`Delete environment ${e.name}?`}
                  description="Resources in this environment stay assigned to the project without an environment."
                  confirmLabel="Delete environment"
                  onConfirm={async () => {
                    await endpoints.deleteEnvironment(project.id, e.id);
                    await qc.invalidateQueries({ queryKey: ["project", project.id] });
                    await qc.invalidateQueries({ queryKey: ["projects"] });
                  }}
                >
                  <Trash2 /> Delete environment
                </ConfirmButton>
              ) : null}
            </div>
            <EnvironmentResources projectId={project.id} environmentId={e.id} />
          </TabsContent>
        ))}
        <TabsContent value="comparison">
          {project.environments.length < 2 ? (
            <Card>
              <CardContent className="py-6 text-sm text-muted-foreground">Add at least two environments to compare them.</CardContent>
            </Card>
          ) : (
            <EnvironmentComparison projectId={project.id} />
          )}
        </TabsContent>
      </Tabs>
      {canManage ? (
        <>
          <EditProjectDialog key={project.id + String(editOpen)} project={project} open={editOpen} onOpenChange={setEditOpen} />
          <AddEnvironmentDialog projectId={project.id} open={envOpen} onOpenChange={setEnvOpen} />
        </>
      ) : null}
    </>
  );
}
