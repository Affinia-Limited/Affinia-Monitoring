import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { KeyValue } from "@/components/common";
import { AlertStatusBadge, SeverityBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { formatDateTime, formatValue, titleCase } from "@/utils/format";

export function AlertDetailDrawer({ alertId, onClose }: { alertId: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const canAck = usePermission(PERMISSIONS.acknowledgeAlerts);
  const query = useQuery({ queryKey: ["alert", alertId], queryFn: () => endpoints.alert(alertId as string), enabled: !!alertId });
  const onDone = () => {
    void qc.invalidateQueries({ queryKey: ["alerts"] });
    void qc.invalidateQueries({ queryKey: ["alert", alertId] });
    void qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const ack = useMutation({ mutationFn: () => endpoints.acknowledgeAlert(alertId as string), onSuccess: onDone });
  const resolve = useMutation({ mutationFn: () => endpoints.resolveAlert(alertId as string), onSuccess: onDone });
  const a = query.data;

  return (
    <Dialog open={!!alertId} onOpenChange={(o) => !o && onClose()}>
      {alertId ? (
        <DialogContent
          side="right"
          title={a?.title ?? "Alert"}
          description={a ? `${a.project_name ?? "Unassigned"} / ${a.environment_name ?? "-"}` : undefined}
          footer={
            a && canAck && a.status !== "resolved" ? (
              <>
                {a.status === "active" ? (
                  <Button variant="outline" disabled={ack.isPending} onClick={() => ack.mutate()}>
                    Acknowledge
                  </Button>
                ) : null}
                <Button disabled={resolve.isPending} onClick={() => resolve.mutate()}>
                  Resolve
                </Button>
              </>
            ) : undefined
          }
        >
          {query.isLoading ? (
            <LoadingBlock />
          ) : query.isError || !a ? (
            <ErrorState error={query.error} />
          ) : (
            <div className="space-y-5">
              <div className="flex gap-2">
                <SeverityBadge severity={a.severity} />
                <AlertStatusBadge status={a.status} />
              </div>
              <KeyValue
                items={[
                  { label: "Resource", value: <Link className="text-primary hover:underline" to={`/resources/${a.resource_id}`}>{a.resource_name}</Link> },
                  { label: "Type", value: a.type_display_name },
                  { label: "Metric", value: a.metric_name },
                  { label: "Current value", value: formatValue(a.current_value, a.unit ?? "") },
                  { label: "Threshold", value: formatValue(a.threshold, a.unit ?? "") },
                  { label: "Started", value: formatDateTime(a.started_at) },
                  { label: "Acknowledged", value: formatDateTime(a.acknowledged_at) },
                  { label: "Resolved", value: formatDateTime(a.resolved_at) },
                  { label: "Source", value: titleCase(a.source) },
                ]}
              />
              {ack.isError ? <ErrorState error={ack.error} /> : null}
              {resolve.isError ? <ErrorState error={resolve.error} /> : null}
              <div>
                <h3 className="mb-2 text-sm font-semibold">Timeline</h3>
                <ol className="relative space-y-3 border-l border-border pl-4">
                  {a.events.map((e) => (
                    <li key={e.id}>
                      <span className="absolute -left-1.5 mt-1.5 size-3 rounded-full border-2 border-card bg-primary" aria-hidden="true" />
                      <p className="text-sm font-medium">{titleCase(e.event_type)}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatDateTime(e.created_at)}
                        {e.message ? ` - ${e.message}` : ""}
                      </p>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          )}
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
