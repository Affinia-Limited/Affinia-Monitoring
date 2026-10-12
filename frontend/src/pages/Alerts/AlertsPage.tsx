import { useSearchParams } from "react-router-dom";
import { AlertsExplorer } from "@/components/AlertsExplorer";
import { PageHeader } from "@/components/common";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAccess } from "@/hooks/useAccess";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { useFilters } from "@/stores/filters";
import { AlertDetailDrawer } from "./AlertDetailDrawer";
import { AlertRules } from "./AlertRules";
import { AlertTemplates } from "./AlertTemplates";
import { AzureExportPanel } from "./AzureExportPanel";
import { EmailNotifications } from "./EmailNotifications";
import { NotificationChannels } from "./NotificationChannels";
import { TeamsNotifications } from "./TeamsNotifications";

export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const { projectId, environmentId } = useFilters();
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  // Notification settings (Teams, email, channels) are organisation-wide: they need access to all projects.
  const { unrestricted } = useAccess();
  const canManageOrg = canManage && unrestricted;
  const allowed = ["templates", "rules", ...(canManage ? ["export"] : []), ...(canManageOrg ? ["teams", "channels", "email"] : [])];
  const tab = allowed.includes(params.get("tab") ?? "") ? (params.get("tab") as string) : "alerts";
  // ?alert=<id> (e.g. from global search) opens the alert drawer.
  const selected = params.get("alert");
  const setSelected = (id: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("alert", id);
        else next.delete("alert");
        return next;
      },
      { replace: true },
    );
  return (
    <>
      <PageHeader title="Alerts" description="Alerts from recommended alert templates and custom rules, across all projects and environments" />
      <Tabs
        value={tab}
        onValueChange={(v) =>
          setParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.set("tab", v);
              return next;
            },
            { replace: true },
          )
        }
      >
        <TabsList aria-label="Alert views">
          <TabsTrigger value="alerts">Alerts</TabsTrigger>
          <TabsTrigger value="templates">Alert templates</TabsTrigger>
          <TabsTrigger value="rules">Custom rules</TabsTrigger>
          {canManageOrg ? <TabsTrigger value="teams">Microsoft Teams</TabsTrigger> : null}
          {canManageOrg ? <TabsTrigger value="email">Email notifications</TabsTrigger> : null}
          {canManageOrg ? <TabsTrigger value="channels">Notification channels</TabsTrigger> : null}
          {canManage ? <TabsTrigger value="export">Export to Azure</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="alerts">
          <AlertsExplorer key={`${projectId}-${environmentId}`} showScopeFilters projectId={projectId} environmentId={environmentId} onSelect={(a) => setSelected(a.id)} />
        </TabsContent>
        <TabsContent value="templates">
          <AlertTemplates />
        </TabsContent>
        <TabsContent value="rules">
          <AlertRules />
        </TabsContent>
        {canManageOrg ? (
          <TabsContent value="teams">
            <TeamsNotifications />
          </TabsContent>
        ) : null}
        {canManageOrg ? (
          <TabsContent value="email">
            <EmailNotifications />
          </TabsContent>
        ) : null}
        {canManageOrg ? (
          <TabsContent value="channels">
            <NotificationChannels />
          </TabsContent>
        ) : null}
        {canManage ? (
          <TabsContent value="export">
            <AzureExportPanel />
          </TabsContent>
        ) : null}
      </Tabs>
      <AlertDetailDrawer alertId={selected} onClose={() => setSelected(null)} />
    </>
  );
}
