import { ArrowRight, Bell } from "lucide-react";
import { Link } from "react-router-dom";
import { HealthText } from "@/components/health";
import { TimeAgo } from "@/components/status";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/states";
import type { Project } from "@/types/api";
import { cn } from "@/utils/cn";
import { paths } from "@/utils/paths";

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
}

/**
 * One project at a glance: overall status, each environment's status and size, alerts and freshness.
 * Environments come from the project's configuration (any number, any names). Only the title and the
 * primary action are links, so the card stays accessible.
 */
export function ProjectCard({ project }: { project: Project }) {
  const empty = project.health.total === 0;
  return (
    <Card className="flex h-full flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold">
            <Link to={paths.project(project.id)} className="hover:underline">
              {project.name}
            </Link>
          </h3>
          {project.description ? <p className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">{project.description}</p> : null}
        </div>
        <HealthText status={empty ? "unknown" : project.status} className="shrink-0" />
      </div>

      {project.environments.length ? (
        <ul className="mt-4 space-y-1.5" aria-label={`${project.name} environments`}>
          {project.environments.map((e) => (
            <li key={e.id} className="grid grid-cols-[minmax(0,1fr)_auto_5.5rem] items-center gap-3 text-sm">
              <Link to={paths.environment(project.id, e.id)} className="truncate text-foreground hover:underline">
                {e.name}
              </Link>
              <HealthText status={e.health.total ? e.status : "unknown"} />
              <span className="tabular text-right text-xs text-muted-foreground">{plural(e.health.total, "resource")}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">No environments configured.</p>
      )}

      <div className="mt-auto" />
      <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 text-xs text-muted-foreground">
        <span>{plural(project.environments.length, "environment")}</span>
        <span>{plural(project.health.total, "resource")}</span>
        <span className={cn("inline-flex items-center gap-1", project.active_alerts ? "font-medium text-critical" : "")}>
          <Bell className="size-3.5" aria-hidden="true" />
          {plural(project.active_alerts, "active alert")}
        </span>
        <span className="ml-auto">
          {project.last_checked_at ? (
            <>
              Checked <TimeAgo value={project.last_checked_at} />
            </>
          ) : (
            "Not checked yet"
          )}
        </span>
      </div>
      <Link
        to={paths.project(project.id)}
        className="mt-3 inline-flex items-center gap-1 self-end text-sm font-medium text-primary hover:underline"
        aria-label={`View project ${project.name}`}
      >
        View project <ArrowRight className="size-4" aria-hidden="true" />
      </Link>
    </Card>
  );
}

export function ProjectCardSkeleton() {
  return (
    <Card className="space-y-4 p-5" aria-hidden="true">
      <div className="flex justify-between">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-20" />
      </div>
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex justify-between">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-28" />
        </div>
      ))}
      <Skeleton className="h-4 w-2/3" />
    </Card>
  );
}
