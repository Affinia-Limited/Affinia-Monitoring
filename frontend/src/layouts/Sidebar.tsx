import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Bell,
  Boxes,
  Cloud,
  FolderKanban,
  LayoutDashboard,
  LayoutGrid,
  ScrollText,
  Settings,
  Users,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { NavLink } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { HealthDot } from "@/components/status";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { cn } from "@/utils/cn";

function Item({ to, icon, label, collapsed, end }: { to: string; icon: ReactNode; label: string; collapsed: boolean; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          "flex h-9 items-center gap-3 rounded-md px-2.5 text-sm font-medium text-sidebar-foreground transition-colors hover:bg-muted [&_svg]:size-4 [&_svg]:shrink-0",
          isActive && "bg-accent text-accent-foreground",
          collapsed && "justify-center px-0",
        )
      }
    >
      {icon}
      {!collapsed ? <span className="truncate">{label}</span> : <span className="sr-only">{label}</span>}
    </NavLink>
  );
}

const PROJECT_LIMIT = 6;

export function Sidebar({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects });
  const canLogs = usePermission(PERMISSIONS.viewLogs);
  const canManageUsers = usePermission(PERMISSIONS.manageUsers);
  const [showAll, setShowAll] = useState(false);
  const allProjects = projects.data ?? [];
  const visibleProjects = showAll ? allProjects : allProjects.slice(0, PROJECT_LIMIT);
  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-1 p-3" onClick={onNavigate}>
      <div className={cn("mb-4 flex items-center gap-2 px-1.5", collapsed && "justify-center px-0")}>
        <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Activity className="size-4" />
        </div>
        {!collapsed ? (
          <div className="leading-tight">
            <div className="text-sm font-semibold">Azure Monitoring</div>
            <div className="text-[11px] text-muted-foreground">Observability platform</div>
          </div>
        ) : null}
      </div>
      <Item to="/" end icon={<LayoutDashboard />} label="Overview" collapsed={collapsed} />
      <Item to="/projects" end icon={<FolderKanban />} label="Projects" collapsed={collapsed} />
      {!collapsed && allProjects.length > 0 ? (
        <div className="mb-1 ml-4 border-l border-border pl-2">
          {visibleProjects.map((p) => (
            <NavLink
              key={p.id}
              to={`/projects/${p.id}`}
              className={({ isActive }) =>
                cn(
                  "flex h-8 items-center gap-2 rounded-md px-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
                  isActive && "bg-muted text-foreground",
                )
              }
            >
              <HealthDot status={p.status} className="size-2" />
              <span className="truncate">{p.name}</span>
            </NavLink>
          ))}
          {allProjects.length > PROJECT_LIMIT ? (
            <button
              type="button"
              className="h-8 w-full rounded-md px-2 text-left text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              onClick={(e) => {
                e.stopPropagation();
                setShowAll((v) => !v);
              }}
            >
              {showAll ? "Show fewer" : `Show all (${allProjects.length})`}
            </button>
          ) : null}
        </div>
      ) : null}
      <Item to="/resources" icon={<Boxes />} label="Resources" collapsed={collapsed} />
      <Item to="/dashboards" icon={<LayoutGrid />} label="Dashboards" collapsed={collapsed} />
      <Item to="/alerts" icon={<Bell />} label="Alerts" collapsed={collapsed} />
      {canLogs ? <Item to="/logs" icon={<ScrollText />} label="Logs" collapsed={collapsed} /> : null}
      <Item to="/azure-connections" icon={<Cloud />} label="Azure Connections" collapsed={collapsed} />
      <div className="mt-auto" />
      {canManageUsers ? <Item to="/settings/users" icon={<Users />} label="Users" collapsed={collapsed} /> : null}
      <Item to="/settings" end icon={<Settings />} label="Settings" collapsed={collapsed} />
    </nav>
  );
}
