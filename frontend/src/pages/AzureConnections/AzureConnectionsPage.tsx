import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Pencil, Plus, RefreshCw, Unplug } from "lucide-react";
import { Fragment, useState } from "react";
import { endpoints } from "@/api/endpoints";
import { ConfirmButton, PageHeader } from "@/components/common";
import { TimeAgo } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Switch } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { Connection } from "@/types/api";
import { formatDateTime, titleCase } from "@/utils/format";
import { AddConnectionWizard } from "./AddConnectionWizard";
import { SyncProgress } from "./SyncProgress";

const STATUS_TONE = { connected: "healthy", pending: "info", error: "critical", disabled: "neutral" } as const;

function HistoryDialog({ connection, onClose }: { connection: Connection; onClose: () => void }) {
  const runs = useQuery({
    queryKey: ["sync-runs", connection.id],
    queryFn: () => endpoints.syncRuns(connection.id),
    refetchInterval: 3000,
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent side="right" title="Synchronisation history" description={connection.name}>
        {runs.isLoading ? (
          <LoadingBlock />
        ) : runs.isError ? (
          <ErrorState error={runs.error} />
        ) : (
          <div className="space-y-5">
            {runs.data?.map((r) => (
              <div key={r.id} className="rounded-md border border-border p-3">
                <div className="mb-2 flex items-center justify-between text-sm">
                  <span className="font-medium">
                    {titleCase(r.trigger)} - {formatDateTime(r.created_at)}
                  </span>
                  <Badge tone={r.status === "succeeded" ? "healthy" : r.status === "failed" ? "critical" : "info"}>{titleCase(r.status)}</Badge>
                </div>
                <SyncProgress run={r} />
                {r.error_message ? <p className="mt-2 text-xs text-critical">{r.error_message}</p> : null}
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function EditDialog({ connection, onClose }: { connection: Connection; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(connection.name);
  const [syncEnabled, setSyncEnabled] = useState(connection.sync_enabled);
  const [extra, setExtra] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      endpoints.updateConnection(connection.id, {
        name,
        sync_enabled: syncEnabled,
        add_subscription_ids: extra.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["connections"] });
      onClose();
    },
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title="Edit connection"
        footer={
          <Button disabled={!name || mutation.isPending} onClick={() => mutation.mutate()}>
            Save
          </Button>
        }
      >
        <div className="space-y-3">
          <Field label="Name" htmlFor="edit-conn-name">
            <Input id="edit-conn-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <div className="flex items-center gap-2">
            <Switch id="edit-conn-sync" checked={syncEnabled} onCheckedChange={setSyncEnabled} />
            <label htmlFor="edit-conn-sync" className="text-sm">
              Scheduled synchronisation
            </label>
          </div>
          <Field label="Add subscription IDs" htmlFor="edit-conn-subs" hint="Optional. One per line or comma-separated.">
            <Input id="edit-conn-subs" value={extra} onChange={(e) => setExtra(e.target.value)} />
          </Field>
          {mutation.isError ? <ErrorState error={mutation.error} /> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function AzureConnectionsPage() {
  const qc = useQueryClient();
  const canConnect = usePermission(PERMISSIONS.connectAzure);
  const canSync = usePermission(PERMISSIONS.syncAzure);
  const [wizard, setWizard] = useState(false);
  const [history, setHistory] = useState<Connection | null>(null);
  const [editing, setEditing] = useState<Connection | null>(null);
  const connections = useQuery({
    queryKey: ["connections"],
    queryFn: endpoints.connections,
    refetchInterval: (q) =>
      (q.state.data as Connection[] | undefined)?.some((c) => c.latest_run && ["queued", "running"].includes(c.latest_run.status)) ? 3000 : false,
  });
  const sync = useMutation({
    mutationFn: (id: string) => endpoints.syncConnection(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["connections"] }),
  });

  return (
    <>
      <PageHeader
        title="Azure Connections"
        description="Subscriptions the platform identity monitors with read-only access"
        actions={
          canConnect ? (
            <Button onClick={() => setWizard(true)}>
              <Plus /> Add Azure subscription
            </Button>
          ) : null
        }
      />
      {sync.isError ? <ErrorState error={sync.error} className="mb-3" /> : null}
      {connections.isLoading ? (
        <LoadingBlock />
      ) : connections.isError ? (
        <ErrorState error={connections.error} />
      ) : (connections.data ?? []).length === 0 ? (
        <Card>
          <EmptyState
            title="No Azure subscriptions connected"
            description={canConnect ? "Add a subscription to start discovering resources." : "Ask an administrator to connect a subscription."}
          />
        </Card>
      ) : (
        <Card>
          <Table>
            <THead>
              <TR>
                <TH>Subscription name</TH>
                <TH>Subscription ID</TH>
                <TH>Tenant</TH>
                <TH>Status</TH>
                <TH>Last sync</TH>
                <TH className="text-right">Resources</TH>
                <TH className="text-right">Actions</TH>
              </TR>
            </THead>
            <tbody>
              {connections.data?.map((c) => (
                <Fragment key={c.id}>
                  <TR className="bg-muted/30">
                    <TD className="font-semibold" colSpan={2}>
                      {c.name}
                      {c.is_demo ? (
                        <Badge tone="info" className="ml-2">
                          Demo data
                        </Badge>
                      ) : null}
                      {c.last_error_message ? <div className="text-xs font-normal text-critical">{c.last_error_message}</div> : null}
                    </TD>
                    <TD className="font-mono text-xs">{c.tenant_id}</TD>
                    <TD>
                      <Badge tone={STATUS_TONE[c.status] ?? "neutral"}>
                        {c.latest_run && ["queued", "running"].includes(c.latest_run.status) ? "Synchronising" : titleCase(c.status)}
                      </Badge>
                    </TD>
                    <TD>
                      <TimeAgo value={c.last_sync_at} />
                    </TD>
                    <TD className="tabular text-right">{c.resource_count}</TD>
                    <TD className="text-right whitespace-nowrap">
                      {canSync ? (
                        <Button size="sm" variant="ghost" disabled={sync.isPending} onClick={() => sync.mutate(c.id)}>
                          <RefreshCw /> Sync now
                        </Button>
                      ) : null}
                      <Button size="icon-sm" variant="ghost" aria-label={`Sync history for ${c.name}`} onClick={() => setHistory(c)}>
                        <History />
                      </Button>
                      {canConnect ? (
                        <>
                          <Button size="icon-sm" variant="ghost" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c)}>
                            <Pencil />
                          </Button>
                          <ConfirmButton
                            title={`Disconnect ${c.name}?`}
                            description={
                              c.is_demo
                                ? "The demo data (resources, dashboards and their health) is removed from the platform."
                                : "Discovered resources and their dashboards are archived. Nothing is changed in Azure."
                            }
                            confirmLabel={c.is_demo ? "Remove demo data" : "Disconnect"}
                            onConfirm={async () => {
                              await endpoints.deleteConnection(c.id);
                              await qc.invalidateQueries();
                            }}
                          >
                            <Unplug />
                            {c.is_demo ? "Remove demo" : "Disconnect"}
                          </ConfirmButton>
                        </>
                      ) : null}
                    </TD>
                  </TR>
                  {c.subscriptions.map((s) => (
                    <TR key={s.id}>
                      <TD className="pl-8">{s.display_name || "Pending verification"}</TD>
                      <TD className="font-mono text-xs">{s.subscription_id}</TD>
                      <TD className="font-mono text-xs text-muted-foreground">{s.tenant_id}</TD>
                      <TD className="text-muted-foreground">{s.state}</TD>
                      <TD>
                        <TimeAgo value={s.last_synced_at} />
                      </TD>
                      <TD className="tabular text-right">{s.resource_count}</TD>
                      <TD />
                    </TR>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
      {canConnect ? <AddConnectionWizard open={wizard} onOpenChange={setWizard} /> : null}
      {history ? <HistoryDialog connection={history} onClose={() => setHistory(null)} /> : null}
      {editing ? <EditDialog connection={editing} onClose={() => setEditing(null)} /> : null}
    </>
  );
}
