import { Link, Route, Routes } from "react-router-dom";
import { EmptyState } from "@/components/ui/states";
import { AppLayout } from "@/layouts/AppLayout";
import { lazyPage } from "./lazyPage";

// One chunk per page, loaded on first visit, so the first screen does not download every page.
const AlertsPage = lazyPage(() => import("@/pages/Alerts/AlertsPage"), "AlertsPage");
const AzureConnectionsPage = lazyPage(() => import("@/pages/AzureConnections/AzureConnectionsPage"), "AzureConnectionsPage");
const OverviewPage = lazyPage(() => import("@/pages/Dashboard/OverviewPage"), "OverviewPage");
const DashboardPage = lazyPage(() => import("@/pages/Dashboards/DashboardPage"), "DashboardPage");
const DashboardsPage = lazyPage(() => import("@/pages/Dashboards/DashboardsPage"), "DashboardsPage");
const LogsPage = lazyPage(() => import("@/pages/Logs/LogsPage"), "LogsPage");
const EnvironmentPage = lazyPage(() => import("@/pages/Projects/EnvironmentPage"), "EnvironmentPage");
const ProjectDetailPage = lazyPage(() => import("@/pages/Projects/ProjectDetailPage"), "ProjectDetailPage");
const ProjectsPage = lazyPage(() => import("@/pages/Projects/ProjectsPage"), "ProjectsPage");
const ResourceByNameRedirect = lazyPage(() => import("@/pages/Resources/ResourceByNameRedirect"), "ResourceByNameRedirect");
const ResourceDetailPage = lazyPage(() => import("@/pages/Resources/ResourceDetailPage"), "ResourceDetailPage");
const ResourcesPage = lazyPage(() => import("@/pages/Resources/ResourcesPage"), "ResourcesPage");
const SettingsPage = lazyPage(() => import("@/pages/Settings/SettingsPage"), "SettingsPage");
const UserDetailPage = lazyPage(() => import("@/pages/Users/UserDetailPage"), "UserDetailPage");
const UsersPage = lazyPage(() => import("@/pages/Users/UsersPage"), "UsersPage");

function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      action={
        <Link className="text-primary hover:underline" to="/">
          Back to the overview
        </Link>
      }
    />
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<OverviewPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="projects/:projectId/environments/:environmentId" element={<EnvironmentPage />} />
        <Route path="resources" element={<ResourcesPage />} />
        <Route path="resources/:resourceId" element={<ResourceDetailPage />} />
        <Route path="app-services/:name" element={<ResourceByNameRedirect />} />
        <Route path="dashboards" element={<DashboardsPage />} />
        <Route path="dashboards/:dashboardId" element={<DashboardPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="logs" element={<LogsPage />} />
        <Route path="azure-connections" element={<AzureConnectionsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/users" element={<UsersPage />} />
        <Route path="settings/users/:userId" element={<UserDetailPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
