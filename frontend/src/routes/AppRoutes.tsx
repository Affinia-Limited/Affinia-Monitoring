import { Link, Route, Routes } from "react-router-dom";
import { EmptyState } from "@/components/ui/states";
import { AppLayout } from "@/layouts/AppLayout";
import { AlertsPage } from "@/pages/Alerts/AlertsPage";
import { AzureConnectionsPage } from "@/pages/AzureConnections/AzureConnectionsPage";
import { OverviewPage } from "@/pages/Dashboard/OverviewPage";
import { DashboardPage } from "@/pages/Dashboards/DashboardPage";
import { DashboardsPage } from "@/pages/Dashboards/DashboardsPage";
import { LivePage } from "@/pages/Live/LivePage";
import { LogsPage } from "@/pages/Logs/LogsPage";
import { EnvironmentPage } from "@/pages/Projects/EnvironmentPage";
import { ProjectDetailPage } from "@/pages/Projects/ProjectDetailPage";
import { ProjectsPage } from "@/pages/Projects/ProjectsPage";
import { ResourceByNameRedirect } from "@/pages/Resources/ResourceByNameRedirect";
import { ResourceDetailPage } from "@/pages/Resources/ResourceDetailPage";
import { ResourcesPage } from "@/pages/Resources/ResourcesPage";
import { SettingsPage } from "@/pages/Settings/SettingsPage";
import { UserDetailPage } from "@/pages/Users/UserDetailPage";
import { UsersPage } from "@/pages/Users/UsersPage";

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
        <Route path="live" element={<LivePage />} />
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
