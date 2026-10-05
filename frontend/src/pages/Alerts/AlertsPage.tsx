import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { AlertTable } from "@/components/AlertTable";
import { PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/form";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { useFilters } from "@/stores/filters";
import type { AlertStatus } from "@/types/api";
import { AlertDetailDrawer } from "./AlertDetailDrawer";
import { AlertRules } from "./AlertRules";
import { NotificationChannels } from "./NotificationChannels";

const PAGE_SIZE = 50;

function AlertList({ status, onSelect }: { status: AlertStatus; onSelect: (id: string) => void }) {
  const { projectId, environmentId } = useFilters();
  const [severity, setSeverity] = useState("");
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["alerts", { status, severity, projectId, environmentId, page }],
    queryFn: () =>
      endpoints.alerts({ status, severity, project_id: projectId, environment_id: environmentId, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
  const pages = Math.max(1, Math.ceil((query.data?.total ?? 0) / PAGE_SIZE));
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3 border-b border-border p-3">
        <div className="space-y-1">
          <Label htmlFor={`severity-${status}`}>Severity</Label>
          <Select id={`severity-${status}`} className="h-8 w-40 text-xs" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </Select>
        </div>
        <p className="pb-1.5 text-xs text-muted-foreground">Project and environment filters in the top bar also apply.</p>
      </div>
      {query.isLoading ? (
        <div className="p-4">
          <LoadingBlock />
        </div>
      ) : query.isError ? (
        <div className="p-4">
          <ErrorState error={query.error} />
        </div>
      ) : (
        <>
          <AlertTable alerts={query.data?.items ?? []} onSelect={(a) => onSelect(a.id)} emptyMessage={`No ${status} alerts.`} />
          {pages > 1 ? (
            <div className="flex items-center justify-end gap-1 border-t border-border px-4 py-2 text-xs text-muted-foreground">
              <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft />
              </Button>
              Page {page} of {pages}
              <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                <ChevronRight />
              </Button>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<string | null>(null);
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const tab = params.get("tab") ?? "active";
  return (
    <>
      <PageHeader title="Alerts" description="Alerts raised by platform alert rules" />
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
          <TabsTrigger value="active">Active</TabsTrigger>
          <TabsTrigger value="acknowledged">Acknowledged</TabsTrigger>
          <TabsTrigger value="resolved">Resolved</TabsTrigger>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          {canManage ? <TabsTrigger value="channels">Notification channels</TabsTrigger> : null}
        </TabsList>
        {(["active", "acknowledged", "resolved"] as const).map((s) => (
          <TabsContent key={s} value={s}>
            <AlertList status={s} onSelect={setSelected} />
          </TabsContent>
        ))}
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
