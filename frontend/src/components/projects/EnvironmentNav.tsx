import { NavLink } from "react-router-dom";
import { HealthDot } from "@/components/status";
import { TIME_FILTER_KEYS, useWithFilters } from "@/hooks/useFilterSearch";
import type { Project } from "@/types/api";
import { cn } from "@/utils/cn";
import { paths } from "@/utils/paths";

/**
 * Project-level navigation: [Overview] [each configured environment]. Links, not tabs, so every
 * environment has its own URL and the context survives reloads and sharing.
 */
export function EnvironmentNav({ project }: { project: Project }) {
  const withTime = useWithFilters(TIME_FILTER_KEYS);
  const item = ({ isActive }: { isActive: boolean }) =>
    cn(
      "inline-flex h-9 items-center gap-2 border-b-2 px-3 text-sm font-medium whitespace-nowrap transition-colors",
      isActive ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
    );
  return (
    <nav aria-label={`${project.name} sections`} className="mb-6 overflow-x-auto border-b border-border">
      <div className="flex min-w-max gap-1">
        <NavLink to={withTime(paths.project(project.id))} end className={item}>
          Overview
        </NavLink>
        {project.environments.map((e) => (
          <NavLink key={e.id} to={withTime(paths.environment(project.id, e.id))} className={item}>
            <HealthDot status={e.health.total ? e.status : "unknown"} className="size-2" />
            {e.name}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
