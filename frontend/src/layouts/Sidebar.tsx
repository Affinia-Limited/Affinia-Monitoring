import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Bell,
  Boxes,
  Cloud,
  FileClock,
  FolderKanban,
  LayoutDashboard,
  LayoutGrid,
  ScrollText,
  Search,
  Settings,
  Users,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { NavLink } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { HealthDot } from "@/components/status";
import { PERMISSIONS, useMe, usePermission } from "@/hooks/useMe";
import { cn } from "@/utils/cn";
import { titleCase } from "@/utils/format";
import { paths } from "@/utils/paths";

export const FOCUS_SEARCH_EVENT = "amp:focus-search";

const itemClass = (collapsed: boolean, active = false) =>
  cn(
    "flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm font-medium text-sidebar-foreground transition-colors hover:bg-muted [&_svg]:size-4 [&_svg]:shrink-0",
    active && "bg-accent text-accent-foreground",
    collapsed && "justify-center px-0",
  );

function Item({
  to,
  icon,
  label,
  collapsed,
  end,
  badge,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  collapsed: boolean;
  end?: boolean;
  badge?: number;
}) {
  return (
    <NavLink to={to} end={end} title={collapsed ? label : undefined} className={({ isActive }) => itemClass(collapsed, isActive)}>
      {icon}
      {!collapsed ? <span className="truncate">{label}</span> : <span className="sr-only">{label}</span>}
      {badge && !collapsed ? (
        <span className="tabular ml-auto rounded-full bg-critical/10 px-1.5 text-xs font-semibold text-critical" aria-label={`${badge} open alerts`}>
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </NavLink>
  );
}

function SectionLabel({ collapsed, children }: { collapsed: boolean; children: string }) {
  if (collapsed) return <div className="my-2 h-px bg-border" aria-hidden="true" />;
  return <p className="mt-4 mb-1 px-2.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{children}</p>;
}

const PROJECT_LIMIT = 8;

export function Sidebar({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects });
  // Same query key as the top-bar bell, so this adds no request.
  const openAlerts = useQuery({
    queryKey: ["alerts", { status: "open", bell: true }],
    queryFn: () => endpoints.alerts({ status: "open", page_size: 1 }),
    refetchInterval: 60_000,
  });
  const { data: me } = useMe();
  const canLogs = usePermission(PERMISSIONS.viewLogs);
  const canManageUsers = usePermission(PERMISSIONS.manageUsers);
  const canAudit = usePermission(PERMISSIONS.viewAudit);
  const [showAll, setShowAll] = useState(false);
  const allProjects = projects.data ?? [];
  const visibleProjects = showAll ? allProjects : allProjects.slice(0, PROJECT_LIMIT);

  return (
    <nav aria-label="Main" className="flex h-full flex-col p-3" onClick={onNavigate}>
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

      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        <Item to="/" end icon={<LayoutDashboard />} label="Overview" collapsed={collapsed} />
        <Item to={paths.projects()} end icon={<FolderKanban />} label="Projects" collapsed={collapsed} />
        {!collapsed && allProjects.length > 0 ? (
          <ul className="mb-1 ml-4 border-l border-border pl-2" aria-label="Projects">
            {visibleProjects.map((p) => (
              <li key={p.id}>
                <NavLink
                  to={paths.project(p.id)}
                  className={({ isActive }) =>
                    cn(
                      "flex h-8 items-center gap-2 rounded-md px-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
                      isActive && "bg-muted text-foreground",
                    )
                  }
                >
                  <HealthDot status={p.health.total ? p.status : "unknown"} className="size-2" />
                  <span className="truncate">{p.name}</span>
                </NavLink>
              </li>
            ))}
            {allProjects.length > PROJECT_LIMIT ? (
              <li>
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
              </li>
            ) : null}
          </ul>
        ) : null}
        <Item to="/alerts" icon={<Bell />} label="Alerts" collapsed={collapsed} badge={openAlerts.data?.total} />
        <Item to="/resources" icon={<Boxes />} label="Resources" collapsed={collapsed} />
        <Item to="/dashboards" icon={<LayoutGrid />} label="Dashboards" collapsed={collapsed} />
        {canLogs ? <Item to="/logs" icon={<ScrollText />} label="Logs" collapsed={collapsed} /> : null}
        <button
          type="button"
          title={collapsed ? "Search (Ctrl K)" : undefined}
          className={itemClass(collapsed)}
          onClick={() => window.dispatchEvent(new Event(FOCUS_SEARCH_EVENT))}
        >
          <Search />
          {!collapsed ? (
            <>
              <span>Search</span>
              <kbd className="ml-auto rounded border border-border px-1.5 text-[10px] text-muted-foreground">Ctrl K</kbd>
            </>
          ) : (
            <span className="sr-only">Search</span>
          )}
        </button>

        <SectionLabel collapsed={collapsed}>Administration</SectionLabel>
        <Item to="/azure-connections" icon={<Cloud />} label="Azure Connections" collapsed={collapsed} />
        {canManageUsers ? <Item to="/settings/users" icon={<Users />} label="Users" collapsed={collapsed} /> : null}
        {canAudit ? <Item to="/settings?tab=audit" icon={<FileClock />} label="Audit log" collapsed={collapsed} /> : null}
        <Item to="/settings" end icon={<Settings />} label="Settings" collapsed={collapsed} />
      </div>

      {me && !collapsed ? (
        <div className="mt-3 border-t border-border px-2.5 pt-3">
          <p className="truncate text-sm font-medium">{me.display_name ?? me.email ?? "Signed in"}</p>
          <p className="truncate text-xs text-muted-foreground">{titleCase(me.role)}</p>
        </div>
      ) : null}
    </nav>
  );
}
