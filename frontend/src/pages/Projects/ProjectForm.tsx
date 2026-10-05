import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "@/api/client";
import { endpoints } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ErrorState } from "@/components/ui/states";
import type { EnvironmentIn, EnvironmentKind } from "@/types/api";
import { slugify } from "@/utils/format";

export const ENV_KINDS: { value: EnvironmentKind; label: string }[] = [
  { value: "development", label: "Development" },
  { value: "uat", label: "UAT" },
  { value: "staging", label: "Staging" },
  { value: "production", label: "Production" },
  { value: "other", label: "Other" },
];

const DEFAULT_ENVS: EnvironmentIn[] = [
  { name: "Development", slug: "dev", kind: "development", tag_values: ["dev", "development"] },
  { name: "UAT", slug: "uat", kind: "uat", tag_values: ["uat"] },
  { name: "Production", slug: "prod", kind: "production", tag_values: ["prod", "production"] },
];

function splitTags(value: string): string[] {
  return value
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export function CreateProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [envs, setEnvs] = useState<EnvironmentIn[]>(DEFAULT_ENVS);

  const mutation = useMutation({
    mutationFn: () =>
      endpoints.createProject({
        name: name.trim(),
        slug,
        description,
        tag_values: splitTags(tags),
        environments: envs.map((e, i) => ({ ...e, sort_order: i })),
      }),
    onSuccess: (project) => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      void qc.invalidateQueries({ queryKey: ["overview"] });
      onOpenChange(false);
      navigate(`/projects/${project.id}`);
    },
  });

  const valid = name.trim().length > 0 && /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(slug) && envs.every((e) => e.name && e.slug);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Create project"
        description="Resources are assigned to projects and environments using Azure tags or connection defaults."
        className="max-w-2xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button disabled={!valid || mutation.isPending} onClick={() => mutation.mutate()}>
              Create project
            </Button>
          </>
        }
      >
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) mutation.mutate();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" htmlFor="project-name">
              <Input
                id="project-name"
                value={name}
                maxLength={200}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!slugTouched) setSlug(slugify(e.target.value));
                }}
                required
              />
            </Field>
            <Field label="Slug" htmlFor="project-slug" hint="Lower-case letters, numbers and dashes.">
              <Input
                id="project-slug"
                value={slug}
                onChange={(e) => {
                  setSlugTouched(true);
                  setSlug(slugify(e.target.value));
                }}
                required
              />
            </Field>
          </div>
          <Field label="Description" htmlFor="project-description">
            <Textarea id="project-description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
          </Field>
          <Field
            label="Tag values"
            htmlFor="project-tags"
            hint="Comma-separated values of the 'project' tag that map a resource to this project. The name and slug always match."
          >
            <Input id="project-tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="crm, crm-app" />
          </Field>
          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-medium">Environments</p>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEnvs([...envs, { name: "", slug: "", kind: "other", tag_values: [] }])}
              >
                <Plus /> Add environment
              </Button>
            </div>
            <div className="space-y-2">
              {envs.map((env, i) => (
                <div key={i} className="grid grid-cols-12 items-end gap-2">
                  <Field label="Name" htmlFor={`env-name-${i}`} className="col-span-4">
                    <Input
                      id={`env-name-${i}`}
                      value={env.name}
                      onChange={(e) =>
                        setEnvs(envs.map((x, j) => (j === i ? { ...x, name: e.target.value, slug: x.slug || slugify(e.target.value) } : x)))
                      }
                    />
                  </Field>
                  <Field label="Slug" htmlFor={`env-slug-${i}`} className="col-span-3">
                    <Input
                      id={`env-slug-${i}`}
                      value={env.slug}
                      onChange={(e) => setEnvs(envs.map((x, j) => (j === i ? { ...x, slug: slugify(e.target.value) } : x)))}
                    />
                  </Field>
                  <Field label="Kind" htmlFor={`env-kind-${i}`} className="col-span-4">
                    <Select
                      id={`env-kind-${i}`}
                      value={env.kind}
                      onChange={(e) => setEnvs(envs.map((x, j) => (j === i ? { ...x, kind: e.target.value as EnvironmentKind } : x)))}
                    >
                      {ENV_KINDS.map((k) => (
                        <option key={k.value} value={k.value}>
                          {k.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="col-span-1"
                    aria-label={`Remove environment ${env.name || i + 1}`}
                    onClick={() => setEnvs(envs.filter((_, j) => j !== i))}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ))}
            </div>
          </div>
          {mutation.isError ? <ErrorState error={mutation.error} /> : null}
          <button type="submit" hidden />
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AddEnvironmentDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [kind, setKind] = useState<EnvironmentKind>("other");
  const [tags, setTags] = useState("");
  const mutation = useMutation({
    mutationFn: () => endpoints.createEnvironment(projectId, { name, slug, kind, tag_values: splitTags(tags) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      onOpenChange(false);
      setName("");
      setSlug("");
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Add environment"
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button disabled={!name || !slug || mutation.isPending} onClick={() => mutation.mutate()}>
              Add environment
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Name" htmlFor="new-env-name">
            <Input
              id="new-env-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setSlug(slugify(e.target.value));
              }}
            />
          </Field>
          <Field label="Slug" htmlFor="new-env-slug">
            <Input id="new-env-slug" value={slug} onChange={(e) => setSlug(slugify(e.target.value))} />
          </Field>
          <Field label="Kind" htmlFor="new-env-kind">
            <Select id="new-env-kind" value={kind} onChange={(e) => setKind(e.target.value as EnvironmentKind)}>
              {ENV_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Tag values" htmlFor="new-env-tags" hint="Comma-separated values of the 'environment' tag.">
            <Input id="new-env-tags" value={tags} onChange={(e) => setTags(e.target.value)} />
          </Field>
          {mutation.isError ? <p className="text-sm text-critical">{errorMessage(mutation.error).message}</p> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
