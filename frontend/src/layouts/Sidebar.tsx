import { useQuery } from "@tanstack/react-query";
import {
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
import { Link, NavLink, useLocation } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import affiniaLogo from "@/assets/affinia-logo.png";
import { HealthDot } from "@/components/status";
import { useWithFilters } from "@/hooks/useFilterSearch";
import { useAccess } from "@/hooks/useAccess";
import { PERMISSIONS, useMe, usePermission } from "@/hooks/useMe";
import { useRefreshInterval } from "@/stores/live";
import { cn } from "@/utils/cn";
import { titleCase } from "@/utils/format";
import { paths } from "@/utils/paths";

export const FOCUS_SEARCH_EVENT = "amp:focus-search";

// Affinia navigation: Honeydew surface, solid Forest Green for the active page (Action Orange in dark mode).
// That colour is reserved for the one current page: the logo mark and avatar use their own styling.
const itemClass = (collapsed: boolean, active = false) =>
  cn(
    "flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm font-medium transition-colors [&_svg]:size-4 [&_svg]:shrink-0",
    active
      ? "bg-sidebar-active font-semibold text-sidebar-active-foreground"
      : "text-sidebar-foreground hover:bg-sidebar-hover",
    collapsed && "justify-center px-0",
  );

function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "")).toUpperCase() || "?";
}

function Item({
  to,
  icon,
  label,
  collapsed,
  end,
  badge,
  active,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  collapsed: boolean;
  end?: boolean;
  badge?: number;
  /**
   * Overrides path matching. Router matching ignores ``?tab=``, so items that share a path
   * (Settings and its Audit log tab, under which Users also lives) decide for themselves.
   */
  active?: boolean;
}) {
  const content = (
    <>
      {icon}
      {!collapsed ? <span className="truncate">{label}</span> : <span className="sr-only">{label}</span>}
      {badge && !collapsed ? (
        <span className="tabular ml-auto rounded-full bg-destructive px-1.5 text-xs font-semibold text-destructive-foreground" aria-label={`${badge} open alerts`}>
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </>
  );
  if (active !== undefined) {
    return (
      <Link to={to} title={collapsed ? label : undefined} aria-current={active ? "page" : undefined} className={itemClass(collapsed, active)}>
        {content}
      </Link>
    );
  }
  return (
    <NavLink to={to} end={end} title={collapsed ? label : undefined} className={({ isActive }) => itemClass(collapsed, isActive)}>
      {content}
    </NavLink>
  );
}

function SectionLabel({ collapsed, children }: { collapsed: boolean; children: string }) {
  if (collapsed) return <div className="my-2 h-px bg-sidebar-border" aria-hidden="true" />;
  return <p className="mt-5 mb-1 px-2.5 text-[11px] font-semibold tracking-wider text-sidebar-muted uppercase">{children}</p>;
}

const PROJECT_LIMIT = 8;

export function Sidebar({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const refetchInterval = useRefreshInterval(60_000);
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, refetchInterval });
  // Same query key as the top-bar bell, so this adds no request.
  const openAlerts = useQuery({
    queryKey: ["alerts", { status: "open", bell: true }],
    queryFn: () => endpoints.alerts({ status: "open", page_size: 1 }),
    refetchInterval,
  });
  const { data: me } = useMe();
  const canLogs = usePermission(PERMISSIONS.viewLogs);
  const canManageUsers = usePermission(PERMISSIONS.manageUsers);
  // Organisation-wide areas (Azure subscriptions, the audit log) need access to all projects.
  const { unrestricted } = useAccess();
  const canAudit = usePermission(PERMISSIONS.viewAudit) && unrestricted;
  const [showAll, setShowAll] = useState(false);
  const withFilters = useWithFilters();
  const { pathname, search } = useLocation();
  const onSettings = pathname === "/settings";
  const auditTab = onSettings && new URLSearchParams(search).get("tab") === "audit";
  const allProjects = projects.data ?? [];
  const visibleProjects = showAll ? allProjects : allProjects.slice(0, PROJECT_LIMIT);

  return (
    <nav aria-label="Main" className="flex h-full flex-col bg-sidebar p-3 text-sidebar-foreground" onClick={onNavigate}>
      <div className={cn("-mx-3 -mt-3 mb-3 flex shrink-0 items-center border-b border-sidebar-border px-4 py-4", collapsed && "justify-center px-0")}>
        {collapsed ? (
          <span
            role="img"
            aria-label="Affinia Monitoring"
            className="flex size-9 items-center justify-center rounded-md bg-[#002729] text-lg font-bold text-[#d5f2e3] dark:bg-[#d5f2e3] dark:text-[#002729]"
          >
            a
          </span>
        ) : (
          <div className="min-w-0">
            <img src={affiniaLogo} alt="Affinia" className="h-7 w-auto dark:brightness-0 dark:invert" />
            <p className="mt-1 text-[11px] font-medium tracking-wider text-sidebar-muted uppercase">Monitoring</p>
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        <Item to={withFilters("/")} end icon={<LayoutDashboard />} label="Overview" collapsed={collapsed} />
        <Item to={withFilters(paths.projects())} end icon={<FolderKanban />} label="Projects" collapsed={collapsed} />
        {!collapsed && allProjects.length > 0 ? (
          <ul className="mb-1 ml-4 border-l border-sidebar-border pl-2" aria-label="Projects">
            {visibleProjects.map((p) => (
              <li key={p.id}>
                <NavLink
                  to={paths.project(p.id)}
                  className={({ isActive }) =>
                    cn(
                      "flex h-8 items-center gap-2 rounded-md px-2 text-sm text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground",
                      isActive && "bg-sidebar-hover font-medium text-sidebar-foreground",
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
                  className="h-8 w-full rounded-md px-2 text-left text-xs text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground"
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
        <Item to={withFilters("/alerts")} icon={<Bell />} label="Alerts" collapsed={collapsed} badge={openAlerts.data?.total} />
        <Item to={withFilters("/resources")} icon={<Boxes />} label="Resources" collapsed={collapsed} />
        <Item to={withFilters("/dashboards")} icon={<LayoutGrid />} label="Dashboards" collapsed={collapsed} />
        {canLogs ? <Item to={withFilters("/logs")} icon={<ScrollText />} label="Logs" collapsed={collapsed} /> : null}
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
              <kbd className="ml-auto rounded border border-sidebar-border px-1.5 text-[10px] text-sidebar-muted">Ctrl K</kbd>
            </>
          ) : (
            <span className="sr-only">Search</span>
          )}
        </button>

        <SectionLabel collapsed={collapsed}>Administration</SectionLabel>
        {unrestricted ? <Item to="/azure-connections" icon={<Cloud />} label="Azure Connections" collapsed={collapsed} /> : null}
        {canManageUsers ? (
          <Item to="/settings/users" icon={<Users />} label="Users" collapsed={collapsed} active={pathname.startsWith("/settings/users")} />
        ) : null}
        {canAudit ? <Item to="/settings?tab=audit" icon={<FileClock />} label="Audit log" collapsed={collapsed} active={auditTab} /> : null}
        <Item to="/settings" icon={<Settings />} label="Settings" collapsed={collapsed} active={onSettings && !auditTab} />
      </div>

      {me ? (
        <div
          className={cn("-mx-3 -mb-3 mt-3 flex shrink-0 items-center gap-3 border-t border-sidebar-border px-4 py-3", collapsed && "justify-center px-0")}
          title={collapsed ? `${me.display_name ?? me.email ?? "Signed in"} (${titleCase(me.role)})` : undefined}
        >
          <span
            aria-hidden="true"
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-border text-xs font-semibold text-sidebar-foreground"
          >
            {initials(me.display_name ?? me.email ?? "?")}
          </span>
          {!collapsed ? (
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{me.display_name ?? me.email ?? "Signed in"}</p>
              <p className="truncate text-xs text-sidebar-muted">{titleCase(me.role)}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </nav>
  );
}
