import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, MessagesSquare, Pencil, Plus, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { endpoints } from "@/api/endpoints";
import { ConfirmButton } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Label, Select, Switch } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import type { TeamsChannel, TeamsChannelIn, TeamsSetup } from "@/types/api";
import { cn } from "@/utils/cn";

const SECRET_NAME = /^[0-9a-zA-Z-]{1,127}$/;

/** The local-development variable that holds a secret: ``org-x-teams-ops`` -> ``SECRET_ORG_X_TEAMS_OPS``. */
export function secretEnvName(secretRef: string): string {
  return `SECRET_${secretRef.toUpperCase().replace(/-/g, "_")}`;
}

const SEVERITY_LABEL: Record<TeamsChannel["min_severity"], string> = {
  critical: "Critical only",
  warning: "Critical and warning",
};

function scopeLabel(channel: TeamsChannel): string {
  if (!channel.project_id) return "All projects";
  return channel.environment_name
    ? `${channel.project_name ?? "Project"} / ${channel.environment_name}`
    : `${channel.project_name ?? "Project"}, all environments`;
}

function Code({ children }: { children: string }) {
  return <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs break-all">{children}</code>;
}

/** How to get a Teams webhook URL and where it goes, for this deployment. */
function SetupGuide({ setup }: { setup: TeamsSetup | undefined }) {
  const [open, setOpen] = useState(false);
  const example = `${setup?.secret_prefix ?? "<prefix>-"}teams-alerts`;
  return (
    <Card>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
      >
        <span>
          <span className="block text-[15px] font-semibold">How to connect a Teams channel</span>
          <span className="block text-xs text-muted-foreground">About 5 minutes. You need permission to add workflows to the channel.</span>
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>
      {open ? (
        <CardContent>
          <ol className="list-decimal space-y-3 pl-5 text-sm">
            <li>
              In Microsoft Teams, open the channel that should receive alerts, select <strong>More options (...)</strong> next to the channel name,
              then <strong>Workflows</strong>.
            </li>
            <li>
              Choose the template <strong>Send webhook alerts to a channel</strong> (also called &ldquo;Post to a channel when a webhook request is
              received&rdquo;), give it a name such as &ldquo;Azure Monitoring alerts&rdquo;, confirm the team and channel, and select{" "}
              <strong>Add workflow</strong>.
            </li>
            <li>
              Copy the URL Teams shows. Treat it like a password: anyone with it can post to the channel. Do not paste it into chats, tickets or this
              page.
            </li>
            <li>
              Store the URL as a secret whose name starts with <Code>{setup?.secret_prefix ?? "<prefix>-"}</Code>, for example <Code>{example}</Code>:
              {setup?.secret_source === "environment" ? (
                <span className="mt-1 block text-muted-foreground">
                  Local development: add <Code>{`${secretEnvName(example)}="<the URL>"`}</Code> to <Code>backend/.env.local</Code> (never committed) and
                  restart the backend.
                </span>
              ) : setup?.secret_source === "key_vault" ? (
                <span className="mt-1 block text-muted-foreground">Add it to the platform&apos;s Azure Key Vault with the URL as the secret value.</span>
              ) : (
                <span className="mt-1 block text-muted-foreground">
                  This deployment has no secret store configured (KEY_VAULT_URL). Ask an administrator to set it up first.
                </span>
              )}
            </li>
            <li>
              Select <strong>New Teams channel</strong> below, enter the secret name, then <strong>Send test message</strong>. A card should appear in
              the channel within a few seconds.
            </li>
          </ol>
        </CardContent>
      ) : null}
    </Card>
  );
}

function TeamsChannelDialog({
  channel,
  setup,
  open,
  onOpenChange,
}: {
  channel: TeamsChannel | null;
  setup: TeamsSetup | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, enabled: open });
  const prefix = setup?.secret_prefix ?? "";
  const [name, setName] = useState(channel?.name ?? "");
  const [secretRef, setSecretRef] = useState(channel?.secret_ref ?? (prefix ? `${prefix}teams-alerts` : ""));
  const [severity, setSeverity] = useState<TeamsChannel["min_severity"]>(channel?.min_severity ?? "critical");
  const [projectId, setProjectId] = useState(channel?.project_id ?? "");
  const [environmentId, setEnvironmentId] = useState(channel?.environment_id ?? "");
  const [notifyResolved, setNotifyResolved] = useState(channel?.notify_resolved ?? true);
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);

  const project = projects.data?.find((p) => p.id === projectId);
  const trimmed = secretRef.trim();
  const secretError = !trimmed
    ? null
    : trimmed.includes("://")
      ? "Enter the secret's name, not the webhook URL itself."
      : !SECRET_NAME.test(trimmed)
        ? "Use letters, digits and hyphens only."
        : prefix && !trimmed.toLowerCase().startsWith(prefix)
          ? `The name must start with ${prefix}`
          : null;
  const canSave = name.trim().length > 0 && trimmed.length > 0 && !secretError;

  const mutation = useMutation({
    mutationFn: () => {
      const body: TeamsChannelIn = {
        name: name.trim(),
        secret_ref: trimmed,
        min_severity: severity,
        notify_resolved: notifyResolved,
        enabled,
        project_id: projectId || null,
        environment_id: environmentId || null,
      };
      return channel ? endpoints.updateTeamsChannel(channel.id, body) : endpoints.createTeamsChannel(body);
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ["teams-channels"] });
      void qc.invalidateQueries({ queryKey: ["channels"] });
      notify({ tone: "success", title: channel ? "Teams channel saved" : "Teams channel added", description: `${saved.name}. Send a test message to check it.` });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={channel ? "Edit Teams channel" : "New Teams channel"}
        description="Posts an alert card to the channel when an alert fires or a resource's health becomes critical (or warning) in the chosen scope."
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button disabled={!canSave || mutation.isPending} onClick={() => mutation.mutate()}>
              {channel ? "Save changes" : "Add channel"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Name" htmlFor="teams-name" hint="How this channel appears here, e.g. the Teams channel's name.">
            <Input id="teams-name" value={name} maxLength={200} placeholder="Platform alerts" onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field
            label="Webhook secret name"
            htmlFor="teams-secret"
            error={secretError}
            hint={
              setup?.secret_source === "environment" && trimmed && !secretError
                ? `Locally, the URL is read from ${secretEnvName(trimmed)} (backend/.env.local).`
                : "The name of the secret that holds the Teams workflow URL. The URL itself is never stored here."
            }
          >
            <Input
              id="teams-secret"
              value={secretRef}
              maxLength={127}
              placeholder={`${prefix || "<prefix>-"}teams-alerts`}
              aria-invalid={secretError ? true : undefined}
              onChange={(e) => setSecretRef(e.target.value)}
            />
          </Field>
          <Field label="Post when" htmlFor="teams-severity">
            <Select id="teams-severity" value={severity} onChange={(e) => setSeverity(e.target.value as TeamsChannel["min_severity"])}>
              <option value="critical">Critical issues only</option>
              <option value="warning">Critical issues and warnings</option>
            </Select>
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Project" htmlFor="teams-project">
              <Select
                id="teams-project"
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value);
                  setEnvironmentId("");
                }}
              >
                <option value="">All projects</option>
                {projects.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Environment" htmlFor="teams-environment">
              <Select id="teams-environment" value={environmentId} disabled={!project} onChange={(e) => setEnvironmentId(e.target.value)}>
                <option value="">All environments</option>
                {project?.environments.map((env) => (
                  <option key={env.id} value={env.id}>
                    {env.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5" checked={notifyResolved} onChange={(e) => setNotifyResolved(e.target.checked)} />
            <span>
              Also post when an alert resolves or a resource recovers
              <span className="block text-xs text-muted-foreground">Recommended, so the channel knows when no action is needed any more.</span>
            </span>
          </label>
          <div className="flex items-center gap-2">
            <Switch id="teams-enabled" checked={enabled} onCheckedChange={setEnabled} />
            <Label htmlFor="teams-enabled">Enabled</Label>
          </div>
          {mutation.isError ? <ErrorState error={mutation.error} compact /> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TeamsChannelRow({ channel, onEdit }: { channel: TeamsChannel; onEdit: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => endpoints.updateTeamsChannel(channel.id, { enabled }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["teams-channels"] }),
    onError: () => notify({ tone: "warning", title: "Could not change the channel", description: "Try again." }),
  });
  const test = useMutation({
    mutationFn: () => endpoints.testChannel(channel.id),
    onSuccess: (result) =>
      notify(
        result.status === "sent"
          ? { tone: "success", title: "Test message posted", description: "Check the Teams channel for the card." }
          : { tone: "warning", title: "Test message not posted", description: result.message },
      ),
    onError: () => notify({ tone: "warning", title: "Test message not posted", description: "The request failed. Try again." }),
  });
  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-2 px-5 py-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold">{channel.name}</h3>
          <Badge tone={channel.min_severity === "critical" ? "critical" : "warning"}>{SEVERITY_LABEL[channel.min_severity]}</Badge>
          {!channel.enabled ? <Badge tone="neutral">Disabled</Badge> : null}
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {scopeLabel(channel)} · {channel.notify_resolved ? "posts recoveries" : "no recovery posts"} · secret <Code>{channel.secret_ref ?? "-"}</Code>
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Switch
          id={`teams-${channel.id}-enabled`}
          checked={channel.enabled}
          disabled={toggle.isPending}
          aria-label={`${channel.enabled ? "Disable" : "Enable"} ${channel.name}`}
          onCheckedChange={(v) => toggle.mutate(v)}
        />
        <Button variant="outline" size="sm" disabled={test.isPending || !channel.enabled} onClick={() => test.mutate()}>
          <Send /> {test.isPending ? "Posting..." : "Send test message"}
        </Button>
        <Button variant="outline" size="sm" onClick={onEdit} aria-label={`Edit ${channel.name}`}>
          <Pencil /> Edit
        </Button>
        <ConfirmButton
          title={`Remove "${channel.name}"?`}
          description="The Teams channel will stop receiving alerts. The Teams workflow and its secret are not deleted."
          confirmLabel="Remove channel"
          onConfirm={async () => {
            await endpoints.deleteTeamsChannel(channel.id);
            await qc.invalidateQueries({ queryKey: ["teams-channels"] });
          }}
        >
          <Trash2 /> Remove
        </ConfirmButton>
      </div>
    </li>
  );
}

export function TeamsNotifications() {
  const setup = useQuery({ queryKey: ["teams-setup"], queryFn: endpoints.teamsSetup, staleTime: 5 * 60_000 });
  const channels = useQuery({ queryKey: ["teams-channels"], queryFn: endpoints.teamsChannels });
  const [editing, setEditing] = useState<TeamsChannel | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const openDialog = (channel: TeamsChannel | null) => {
    setEditing(channel);
    setDialogOpen(true);
  };

  return (
    <div className="space-y-4">
      <SetupGuide setup={setup.data} />
      <Card>
        <CardHeader
          title="Microsoft Teams"
          description="Teams channels that receive an alert card when something goes wrong: every alert and every change to critical (or warning) in their scope, and optionally recoveries."
          actions={
            <Button size="sm" onClick={() => openDialog(null)}>
              <Plus /> New Teams channel
            </Button>
          }
        />
        {channels.isLoading ? (
          <CardContent>
            <LoadingBlock label="Loading Teams channels" />
          </CardContent>
        ) : channels.isError ? (
          <CardContent>
            <ErrorState error={channels.error} title="Unable to load Teams channels." onRetry={() => void channels.refetch()} />
          </CardContent>
        ) : (channels.data ?? []).length === 0 ? (
          <EmptyState
            icon={<MessagesSquare className="size-10" />}
            title="No Teams channels yet"
            description="Connect a Teams channel (see the steps above) so your team sees critical issues where they already work."
            action={
              <Button onClick={() => openDialog(null)}>
                <Plus /> New Teams channel
              </Button>
            }
          />
        ) : (
          <ul className="divide-y divide-border/70 border-t border-border/70">
            {channels.data?.map((channel) => (
              <TeamsChannelRow key={channel.id} channel={channel} onEdit={() => openDialog(channel)} />
            ))}
          </ul>
        )}
      </Card>
      {dialogOpen ? (
        <TeamsChannelDialog key={editing?.id ?? "new"} channel={editing} setup={setup.data} open={dialogOpen} onOpenChange={setDialogOpen} />
      ) : null}
    </div>
  );
}
