import { useQuery } from "@tanstack/react-query";
import { Bell, LogOut, Menu, Monitor, Moon, PanelLeft, Sun, User } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { EnvironmentPill } from "@/components/status";
import { TimeRangePicker } from "@/components/TimeRangePicker";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/menu";
import { useMe } from "@/hooks/useMe";
import { useSignOut } from "@/hooks/useSignOut";
import { useFilters } from "@/stores/filters";
import { type ThemePreference, useTheme } from "@/stores/theme";
import { titleCase } from "@/utils/format";
import { GlobalSearch } from "./GlobalSearch";

export function ProjectEnvironmentSelect() {
  const { projectId, environmentId, setProject, setEnvironment } = useFilters();
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects });
  const project = projects.data?.find((p) => p.id === projectId);
  return (
    <div className="hidden items-center gap-2 lg:flex">
      <Select
        aria-label="Project"
        className="h-8 w-auto min-w-40 max-w-60 text-xs"
        value={projectId ?? ""}
        onChange={(e) => setProject(e.target.value || null)}
      >
        <option value="">All projects</option>
        {projects.data?.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Environment"
        className="h-8 w-auto min-w-40 max-w-60 text-xs"
        value={environmentId ?? ""}
        disabled={!project}
        onChange={(e) => setEnvironment(e.target.value || null)}
      >
        <option value="">All environments</option>
        {project?.environments.map((e) => (
          <option key={e.id} value={e.id}>
            {e.name}
          </option>
        ))}
      </Select>
    </div>
  );
}

function ThemeMenu() {
  const { preference, resolved, setPreference } = useTheme();
  const options: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
  ];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Theme: ${preference}`}>
          {resolved === "dark" ? <Moon /> : <Sun />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {options.map((o) => (
          <DropdownMenuItem key={o.value} onSelect={() => setPreference(o.value)} aria-checked={preference === o.value}>
            <o.icon />
            {o.label}
            {preference === o.value ? <span className="ml-auto text-xs text-muted-foreground">Selected</span> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Notifications() {
  const alerts = useQuery({
    queryKey: ["alerts", { status: "open", bell: true }],
    queryFn: () => endpoints.alerts({ status: "open", page_size: 1 }),
    refetchInterval: 60_000,
  });
  const count = alerts.data?.total ?? 0;
  return (
    <Button variant="ghost" size="icon-sm" asChild>
      <Link to="/alerts" aria-label={`${count} open alerts`} className="relative">
        <Bell />
        {count > 0 ? (
          <span className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-critical px-1 text-center text-[10px] leading-4 font-semibold text-white">
            {count > 99 ? "99+" : count}
          </span>
        ) : null}
      </Link>
    </Button>
  );
}

function ModePills() {
  const { data: me } = useMe();
  if (!me) return null;
  return (
    <div className="mr-1 flex items-center gap-1.5">
      {me.auth_mode === "dev" ? (
        <EnvironmentPill label="Dev sign-in" tooltip="Development authentication: Entra ID sign-in is disabled. Never use outside local development." />
      ) : null}
      {me.azure_provider === "mock" ? (
        <EnvironmentPill label="Demo data" tooltip="The mock Azure provider is active. Resources, metrics and logs are synthetic." />
      ) : null}
    </div>
  );
}

function UserMenu() {
  const { data: me } = useMe();
  const signOut = useSignOut();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label="User menu" className="gap-2">
          <span className="flex size-7 items-center justify-center rounded-full bg-muted">
            <User className="size-4" />
          </span>
          <span className="hidden max-w-36 truncate text-left xl:block">{me?.display_name ?? me?.email ?? "Account"}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-60">
        <DropdownMenuLabel>
          <div className="truncate font-medium text-foreground">{me?.display_name ?? "Signed in"}</div>
          <div className="truncate">{me?.email}</div>
          <div className="mt-1">Role: {me ? titleCase(me.role) : "-"}</div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/settings">Settings</Link>
        </DropdownMenuItem>
        {me?.auth_mode === "entra" ? (
          <DropdownMenuItem onSelect={() => void signOut()}>
            <LogOut />
            Sign out
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Pages whose URL already fixes the project/environment show breadcrumbs instead of the global pickers. */
const CONTEXT_ROUTES = [/^\/projects\/[^/]+/, /^\/resources\/[^/]+/, /^\/dashboards\/[^/]+/, /^\/settings/, /^\/azure-connections/];
/** Pages with a fixed time window (Live always shows the last hour). */
const FIXED_WINDOW_ROUTES = [/^\/live$/];

export function TopBar({ onToggleSidebar, onOpenMobileNav }: { onToggleSidebar: () => void; onOpenMobileNav: () => void }) {
  const { pathname } = useLocation();
  const contextKnown = CONTEXT_ROUTES.some((r) => r.test(pathname));
  const fixedWindow = FIXED_WINDOW_ROUTES.some((r) => r.test(pathname));
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-card/95 px-3 backdrop-blur md:px-4">
      <Button variant="ghost" size="icon-sm" className="md:hidden" aria-label="Open navigation" onClick={onOpenMobileNav}>
        <Menu />
      </Button>
      <Button variant="ghost" size="icon-sm" className="hidden md:inline-flex" aria-label="Toggle sidebar" onClick={onToggleSidebar}>
        <PanelLeft />
      </Button>
      <GlobalSearch />
      <div className="ml-auto flex items-center gap-1.5">
        <ModePills />
        {contextKnown ? null : <ProjectEnvironmentSelect />}
        {fixedWindow ? null : <TimeRangePicker />}
        <Notifications />
        <ThemeMenu />
        <UserMenu />
      </div>
    </header>
  );
}
