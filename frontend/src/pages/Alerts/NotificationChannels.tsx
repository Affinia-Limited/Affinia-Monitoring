import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { endpoints } from "@/api/endpoints";
import { ConfirmButton } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import type { NotificationChannel } from "@/types/api";

const TYPES: { value: NotificationChannel["channel_type"]; label: string }[] = [
  { value: "teams", label: "Microsoft Teams" },
  { value: "slack", label: "Slack" },
  { value: "webhook", label: "Webhook" },
  { value: "email", label: "Email (not yet available)" },
];

function CreateChannelDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [type, setType] = useState<NotificationChannel["channel_type"]>("teams");
  const [secretRef, setSecretRef] = useState("");
  const mutation = useMutation({
    mutationFn: () => endpoints.createChannel({ name, channel_type: type, enabled: true, secret_ref: secretRef || null, config: {} }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["channels"] });
      onOpenChange(false);
      setName("");
      setSecretRef("");
    },
  });
  const secretValid = type === "email" || /^[0-9a-zA-Z-]{1,127}$/.test(secretRef);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Add notification channel"
        footer={
          <Button disabled={!name || !secretValid || mutation.isPending} onClick={() => mutation.mutate()}>
            Add channel
          </Button>
        }
      >
        <div className="space-y-3">
          <Field label="Name" htmlFor="channel-name">
            <Input id="channel-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Type" htmlFor="channel-type">
            <Select id="channel-type" value={type} onChange={(e) => setType(e.target.value as NotificationChannel["channel_type"])}>
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Field>
          {type !== "email" ? (
            <Field
              label="Key Vault secret name"
              htmlFor="channel-secret"
              hint="Store the webhook URL as a secret in the platform's Azure Key Vault and enter the secret's name here. The URL itself is never stored in the database or shown in the browser."
            >
              <Input id="channel-secret" value={secretRef} placeholder="teams-ops-webhook" onChange={(e) => setSecretRef(e.target.value.trim())} />
            </Field>
          ) : null}
          {mutation.isError ? <ErrorState error={mutation.error} /> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function NotificationChannels() {
  const qc = useQueryClient();
  const channels = useQuery({ queryKey: ["channels"], queryFn: endpoints.channels });
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<Record<string, string>>({});
  const test = useMutation({
    mutationFn: (id: string) => endpoints.testChannel(id),
    onSuccess: (r, id) => setResult((s) => ({ ...s, [id]: r.message })),
  });
  return (
    <Card>
      <CardHeader
        title="Notification channels"
        description="Where alert notifications are delivered"
        actions={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus /> Add channel
          </Button>
        }
      />
      <CardContent className="px-0">
        {channels.isLoading ? (
          <div className="px-4">
            <LoadingBlock />
          </div>
        ) : channels.isError ? (
          <div className="px-4">
            <ErrorState error={channels.error} />
          </div>
        ) : (channels.data ?? []).length === 0 ? (
          <EmptyState title="No notification channels" description="Alerts are still shown in the platform without a channel." />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Type</TH>
                <TH>Key Vault secret</TH>
                <TH>Status</TH>
                <TH className="text-right">Actions</TH>
              </TR>
            </THead>
            <tbody>
              {channels.data?.map((c) => (
                <TR key={c.id}>
                  <TD className="font-medium">{c.name}</TD>
                  <TD>{TYPES.find((t) => t.value === c.channel_type)?.label ?? c.channel_type}</TD>
                  <TD className="font-mono text-xs">{c.secret_ref ?? "-"}</TD>
                  <TD>
                    {c.enabled ? <Badge tone="healthy">Enabled</Badge> : <Badge>Disabled</Badge>}
                    {result[c.id] ? <div className="mt-1 text-xs text-muted-foreground">{result[c.id]}</div> : null}
                  </TD>
                  <TD className="text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" disabled={test.isPending} onClick={() => test.mutate(c.id)}>
                      <Send /> Test
                    </Button>
                    <ConfirmButton
                      title={`Delete channel ${c.name}?`}
                      description="Rules using this channel stop notifying it."
                      confirmLabel="Delete channel"
                      onConfirm={async () => {
                        await endpoints.deleteChannel(c.id);
                        await qc.invalidateQueries({ queryKey: ["channels"] });
                      }}
                    >
                      <Trash2 />
                      <span className="sr-only">Delete {c.name}</span>
                    </ConfirmButton>
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
        {test.isError ? (
          <div className="px-4 pt-2">
            <ErrorState error={test.error} />
          </div>
        ) : null}
      </CardContent>
      <CreateChannelDialog open={open} onOpenChange={setOpen} />
    </Card>
  );
}
