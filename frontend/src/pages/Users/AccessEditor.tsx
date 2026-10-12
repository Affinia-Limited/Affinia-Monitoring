import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { endpoints } from "@/api/endpoints";
import { Input } from "@/components/ui/form";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import { useDebounce } from "@/hooks/useDebounce";
import type { AssignableScope } from "@/types/api";
import {
  type AccessSelection,
  type EnvironmentSelection,
  type ProjectSelection,
  type ResourcePick,
  summariseSelection,
} from "@/utils/access";
import { cn } from "@/utils/cn";

const RESOURCE_LIMIT = 50;

function Choice({
  name,
  checked,
  onChange,
  children,
  disabled,
}: {
  name: string;
  checked: boolean;
  onChange: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={cn("inline-flex items-center gap-2 text-sm", disabled && "opacity-50")}>
      <input type="radio" name={name} checked={checked} disabled={disabled} onChange={onChange} />
      {children}
    </label>
  );
}

function ResourcePicker({
  environmentId,
  environmentName,
  value,
  onChange,
}: {
  environmentId: string;
  environmentName: string;
  value: ResourcePick;
  onChange: (next: ResourcePick) => void;
}) {
  const [text, setText] = useState("");
  const q = useDebounce(text.trim(), 300);
  const resources = useQuery({
    queryKey: ["assignable-resources", environmentId, q],
    queryFn: () => endpoints.assignableResources(environmentId, { q: q || undefined, limit: RESOURCE_LIMIT }),
    placeholderData: keepPreviousData,
  });
  const chosen = Object.entries(value);
  const toggle = (id: string, name: string) => {
    const next = { ...value };
    if (next[id]) delete next[id];
    else next[id] = name;
    onChange(next);
  };
  return (
    <div className="mt-2 space-y-2 rounded-md border border-border bg-muted/30 p-3">
      {chosen.length ? (
        <ul className="flex flex-wrap gap-1.5" aria-label={`Chosen resources in ${environmentName}`}>
          {chosen.map(([id, name]) => (
            <li key={id} className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-xs">
              {name}
              <button type="button" aria-label={`Remove ${name}`} className="text-muted-foreground hover:text-foreground" onClick={() => toggle(id, name)}>
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input
          aria-label={`Search resources in ${environmentName}`}
          placeholder="Search resources..."
          className="h-8 pl-8"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      {resources.isLoading ? (
        <LoadingBlock label="Loading resources" />
      ) : resources.isError ? (
        <ErrorState error={resources.error} compact />
      ) : (resources.data ?? []).length === 0 ? (
        <p className="text-xs text-muted-foreground">No resources match.</p>
      ) : (
        <ul className="max-h-48 space-y-1 overflow-y-auto" aria-label={`Resources in ${environmentName}`}>
          {resources.data?.map((r) => (
            <li key={r.id}>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={!!value[r.id]} onChange={() => toggle(r.id, r.name)} />
                <span className="truncate">{r.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {r.type_display_name}
                  {r.monitored ? "" : " · not monitored"}
                </span>
              </label>
            </li>
          ))}
          {(resources.data?.length ?? 0) >= RESOURCE_LIMIT ? (
            <li className="text-xs text-muted-foreground">Showing the first {RESOURCE_LIMIT}. Search to narrow down.</li>
          ) : null}
        </ul>
      )}
    </div>
  );
}

function EnvironmentRow({
  project,
  environment,
  value,
  onChange,
}: {
  project: AssignableScope["projects"][number];
  environment: AssignableScope["projects"][number]["environments"][number];
  value: EnvironmentSelection | undefined;
  onChange: (next: EnvironmentSelection | undefined) => void;
}) {
  const checked = value !== undefined;
  const name = `env-mode-${environment.id}`;
  return (
    <li>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={checked} onChange={() => onChange(checked ? undefined : environment.full ? "all" : {})} />
        <span className="font-medium">{environment.name}</span>
      </label>
      {checked ? (
        <div className="mt-1 ml-6">
          <div className="flex flex-wrap gap-x-4 gap-y-1" role="radiogroup" aria-label={`Resources in ${project.name} / ${environment.name}`}>
            {environment.full ? (
              <Choice name={name} checked={value === "all"} onChange={() => onChange("all")}>
                All resources
              </Choice>
            ) : null}
            <Choice name={name} checked={value !== "all"} onChange={() => onChange(value === "all" ? {} : value)}>
              Specific resources
            </Choice>
          </div>
          {value !== "all" && value ? (
            <ResourcePicker environmentId={environment.id} environmentName={`${project.name} / ${environment.name}`} value={value} onChange={onChange} />
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function ProjectRow({
  project,
  value,
  onChange,
}: {
  project: AssignableScope["projects"][number];
  value: ProjectSelection | undefined;
  onChange: (next: ProjectSelection | undefined) => void;
}) {
  const checked = value !== undefined;
  const name = `project-mode-${project.id}`;
  const envs = value && value !== "all" ? value : {};
  return (
    <li className="rounded-md border border-border p-3">
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={checked} onChange={() => onChange(checked ? undefined : project.full ? "all" : {})} />
        <span className="font-semibold">{project.name}</span>
      </label>
      {checked ? (
        <div className="mt-2 ml-6 space-y-2">
          <div className="flex flex-wrap gap-x-4 gap-y-1" role="radiogroup" aria-label={`Environments in ${project.name}`}>
            {project.full ? (
              <Choice name={name} checked={value === "all"} onChange={() => onChange("all")}>
                All environments
              </Choice>
            ) : null}
            <Choice name={name} checked={value !== "all"} onChange={() => onChange(value === "all" ? {} : value)}>
              Specific environments
            </Choice>
          </div>
          {value !== "all" ? (
            project.environments.length ? (
              <ul className="space-y-2">
                {project.environments.map((env) => (
                  <EnvironmentRow
                    key={env.id}
                    project={project}
                    environment={env}
                    value={envs[env.id]}
                    onChange={(next) => {
                      const copy = { ...envs };
                      if (next === undefined) delete copy[env.id];
                      else copy[env.id] = next;
                      onChange(copy);
                    }}
                  />
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">This project has no environments you can grant.</p>
            )
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Chooses what a user may see: all projects, or specific projects, environments and resources.
 * Only offers what the signed-in user may grant (``/users/assignable-scope``); the API re-checks.
 */
export function AccessEditor({
  value,
  onChange,
  isSuperAdmin,
  error,
}: {
  value: AccessSelection;
  onChange: (next: AccessSelection) => void;
  isSuperAdmin: boolean;
  error?: string | null;
}) {
  const scope = useQuery({ queryKey: ["assignable-scope"], queryFn: endpoints.assignableScope, staleTime: 60_000, enabled: !isSuperAdmin });

  if (isSuperAdmin) {
    return (
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">Access</legend>
        <p className="text-sm text-muted-foreground">Super Admins always have access to everything.</p>
      </fieldset>
    );
  }
  if (scope.isLoading) return <LoadingBlock label="Loading projects you can grant" />;
  if (scope.isError || !scope.data) return <ErrorState error={scope.error} title="Unable to load the projects you can grant." compact />;
  const s = scope.data;
  const all = s.unrestricted && value.all;
  return (
    <fieldset className="space-y-3" aria-describedby="access-summary">
      <legend className="text-sm font-medium">Access</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1" role="radiogroup" aria-label="Projects">
        {s.unrestricted ? (
          <Choice name="access-mode" checked={all} onChange={() => onChange({ all: true, projects: {} })}>
            All projects
          </Choice>
        ) : null}
        <Choice name="access-mode" checked={!all} onChange={() => onChange({ all: false, projects: value.all ? {} : value.projects })}>
          Specific projects
        </Choice>
      </div>
      {!all ? (
        s.projects.length ? (
          <ul className="space-y-2">
            {s.projects.map((project) => (
              <ProjectRow
                key={project.id}
                project={project}
                value={value.projects[project.id]}
                onChange={(next) => {
                  const projects = { ...value.projects };
                  if (next === undefined) delete projects[project.id];
                  else projects[project.id] = next;
                  onChange({ all: false, projects });
                }}
              />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">There are no projects you can grant access to.</p>
        )
      ) : (
        <p className="text-xs text-muted-foreground">Includes projects created later.</p>
      )}
      <p id="access-summary" className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Summary:</span> {summariseSelection(value, s)}
      </p>
      {error ? (
        <p role="alert" className="text-sm text-critical">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
