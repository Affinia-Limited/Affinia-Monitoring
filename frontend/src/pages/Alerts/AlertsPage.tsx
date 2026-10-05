import { useSearchParams } from "react-router-dom";
import { AlertsExplorer } from "@/components/AlertsExplorer";
import { PageHeader } from "@/components/common";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { useFilters } from "@/stores/filters";
import { AlertDetailDrawer } from "./AlertDetailDrawer";
import { AlertRules } from "./AlertRules";
import { NotificationChannels } from "./NotificationChannels";

export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const { projectId, environmentId } = useFilters();
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const tab = ["rules", "channels"].includes(params.get("tab") ?? "") ? (params.get("tab") as string) : "alerts";
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
      <PageHeader title="Alerts" description="Alerts raised by platform alert rules across all projects and environments" />
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
          <TabsTrigger value="rules">Rules</TabsTrigger>
          {canManage ? <TabsTrigger value="channels">Notification channels</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="alerts">
          <AlertsExplorer key={`${projectId}-${environmentId}`} showScopeFilters projectId={projectId} environmentId={environmentId} onSelect={(a) => setSelected(a.id)} />
        </TabsContent>
        <TabsContent value="rules">
          <AlertRules />
        </TabsContent>
        {canManage ? (
          <TabsContent value="channels">
            <NotificationChannels />
          </TabsContent>
        ) : null}
      </Tabs>
      <AlertDetailDrawer alertId={selected} onClose={() => setSelected(null)} />
    </>
  );
}
