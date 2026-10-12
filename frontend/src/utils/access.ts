import type { AccessGrant, AccessGrantIn, AssignableScope } from "@/types/api";

/**
 * The access editor's working state. ``all`` = every project. Otherwise each chosen project maps to
 * "all environments" (``"all"``) or to its chosen environments, each of which is "all resources"
 * (``"all"``) or a set of chosen resource ids (with names kept for display).
 */
export type ResourcePick = Record<string, string>; // resource id -> name
export type EnvironmentSelection = "all" | ResourcePick;
export type ProjectSelection = "all" | Record<string, EnvironmentSelection>;
export interface AccessSelection {
  all: boolean;
  projects: Record<string, ProjectSelection>;
}

export const EMPTY_SELECTION: AccessSelection = { all: false, projects: {} };

/** Builds the editor state from existing grants (the API stores the minimal set). */
export function selectionFromGrants(grants: Pick<AccessGrant, "project_id" | "environment_id" | "resource_id" | "resource_name">[]): AccessSelection {
  if (grants.some((g) => g.project_id === null)) return { all: true, projects: {} };
  const projects: Record<string, ProjectSelection> = {};
  for (const g of grants) {
    if (!g.project_id) continue;
    if (!g.environment_id) {
      projects[g.project_id] = "all";
      continue;
    }
    const project = projects[g.project_id];
    if (project === "all") continue;
    const envs = project ?? {};
    projects[g.project_id] = envs;
    if (!g.resource_id) {
      envs[g.environment_id] = "all";
      continue;
    }
    const env = envs[g.environment_id];
    if (env === "all") continue;
    envs[g.environment_id] = { ...(env ?? {}), [g.resource_id]: g.resource_name ?? g.resource_id };
  }
  return { all: false, projects };
}

/** The minimal grants for a selection: whole projects, whole environments, then single resources. */
export function grantsFromSelection(selection: AccessSelection): AccessGrantIn[] {
  if (selection.all) return [{ project_id: null }];
  const grants: AccessGrantIn[] = [];
  for (const [projectId, project] of Object.entries(selection.projects)) {
    if (project === "all") {
      grants.push({ project_id: projectId });
      continue;
    }
    for (const [environmentId, env] of Object.entries(project)) {
      if (env === "all") grants.push({ project_id: projectId, environment_id: environmentId });
      else for (const resourceId of Object.keys(env)) grants.push({ project_id: projectId, environment_id: environmentId, resource_id: resourceId });
    }
  }
  return grants;
}

/** First problem with a selection, or null. Super Admins need no selection. */
export function selectionError(selection: AccessSelection, isSuperAdmin: boolean): string | null {
  if (isSuperAdmin || selection.all) return null;
  const projects = Object.entries(selection.projects);
  if (projects.length === 0) return "Choose at least one project, or All projects.";
  for (const [, project] of projects) {
    if (project === "all") continue;
    const envs = Object.entries(project);
    if (envs.length === 0) return "For each chosen project, choose All environments or at least one environment.";
    for (const [, env] of envs) {
      if (env !== "all" && Object.keys(env).length === 0) return "For each environment limited to specific resources, choose at least one resource.";
    }
  }
  return null;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Plain-English access summary, e.g. "CRM: all environments · PRISM / Production: 2 resources".
 * Names come from the grants themselves or, for a selection being edited, from the assignable scope.
 */
export function summariseGrants(
  grants: Pick<AccessGrant, "project_id" | "project_name" | "environment_id" | "environment_name" | "resource_id">[],
): string {
  if (grants.some((g) => g.project_id === null)) return "All projects";
  if (grants.length === 0) return "No access";
  const parts: string[] = [];
  const wholeProjects = new Set(grants.filter((g) => g.project_id && !g.environment_id).map((g) => g.project_id));
  const seen = new Set<string>();
  for (const g of grants) {
    if (!g.project_id) continue;
    const project = g.project_name ?? "Project";
    if (wholeProjects.has(g.project_id)) {
      if (!seen.has(g.project_id)) parts.push(`${project}: all environments`);
      seen.add(g.project_id);
      continue;
    }
    const key = `${g.project_id}/${g.environment_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const env = `${project} / ${g.environment_name ?? "Environment"}`;
    const wholeEnv = grants.some((x) => x.environment_id === g.environment_id && !x.resource_id);
    const resources = grants.filter((x) => x.environment_id === g.environment_id && x.resource_id).length;
    parts.push(wholeEnv ? `${env}: all resources` : `${env}: ${plural(resources, "resource")}`);
  }
  return parts.join(" · ");
}

/** Summary of a selection being edited, using the names from the assignable scope. */
export function summariseSelection(selection: AccessSelection, scope: AssignableScope | undefined): string {
  if (selection.all) return "All projects";
  const grants = grantsFromSelection(selection).map((g) => {
    const project = scope?.projects.find((p) => p.id === g.project_id);
    const env = project?.environments.find((e) => e.id === g.environment_id);
    return {
      project_id: g.project_id,
      project_name: project?.name ?? null,
      environment_id: g.environment_id ?? null,
      environment_name: env?.name ?? null,
      resource_id: g.resource_id ?? null,
    };
  });
  return grants.length ? summariseGrants(grants) : "Nothing selected yet";
}
