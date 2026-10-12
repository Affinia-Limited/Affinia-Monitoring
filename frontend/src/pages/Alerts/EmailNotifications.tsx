import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, Mail, Pencil, Plus, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { endpoints } from "@/api/endpoints";
import { ConfirmButton } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Label, Select, Switch, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import type { EmailList, EmailListIn } from "@/types/api";

export const MAX_RECIPIENTS = 50;
// Mirrors the API's check; the server remains the authority.
const EMAIL = /^(?=.{3,254}$)(?=[^@]{1,64}@)[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;

/** Splits pasted text (new lines, commas, semicolons, spaces) into lower-cased, de-duplicated addresses. */
export function parseRecipients(text: string): { valid: string[]; invalid: string[] } {
  const valid: string[] = [];
  const invalid: string[] = [];
  for (const raw of text.split(/[\s,;]+/)) {
    const address = raw.trim().toLowerCase();
    if (!address) continue;
    if (!EMAIL.test(address)) {
      if (!invalid.includes(raw.trim())) invalid.push(raw.trim());
    } else if (!valid.includes(address)) {
      valid.push(address);
    }
  }
  return { valid, invalid };
}

const SEVERITY_LABEL: Record<EmailList["min_severity"], string> = {
  critical: "Critical only",
  warning: "Critical and warning",
};

function scopeLabel(list: EmailList): string {
  if (!list.project_id) return "All projects";
  return list.environment_name ? `${list.project_name ?? "Project"} / ${list.environment_name}` : `${list.project_name ?? "Project"}, all environments`;
}

function EmailListDialog({ list, open, onOpenChange }: { list: EmailList | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, enabled: open });
  const [name, setName] = useState(list?.name ?? "");
  const [recipientsText, setRecipientsText] = useState(list?.recipients.join("\n") ?? "");
  const [severity, setSeverity] = useState<EmailList["min_severity"]>(list?.min_severity ?? "critical");
  const [projectId, setProjectId] = useState(list?.project_id ?? "");
  const [environmentId, setEnvironmentId] = useState(list?.environment_id ?? "");
  const [notifyResolved, setNotifyResolved] = useState(list?.notify_resolved ?? true);
  const [enabled, setEnabled] = useState(list?.enabled ?? true);
  const [touched, setTouched] = useState(false);

  const { valid, invalid } = parseRecipients(recipientsText);
  const project = projects.data?.find((p) => p.id === projectId);
  const recipientError = invalid.length
    ? `Not valid email address${invalid.length === 1 ? "" : "es"}: ${invalid.slice(0, 3).join(", ")}${invalid.length > 3 ? ` and ${invalid.length - 3} more` : ""}`
    : valid.length > MAX_RECIPIENTS
      ? `A list can have at most ${MAX_RECIPIENTS} recipients (${valid.length} entered).`
      : touched && valid.length === 0
        ? "Add at least one recipient."
        : null;
  const canSave = name.trim().length > 0 && valid.length > 0 && !recipientError;

  const mutation = useMutation({
    mutationFn: () => {
      const body: EmailListIn = {
        name: name.trim(),
        recipients: valid,
        min_severity: severity,
        notify_resolved: notifyResolved,
        enabled,
        project_id: projectId || null,
        environment_id: environmentId || null,
      };
      return list ? endpoints.updateEmailList(list.id, body) : endpoints.createEmailList(body);
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ["email-lists"] });
      notify({ tone: "success", title: list ? "Email list saved" : "Email list created", description: `${saved.name}: ${saved.recipients.length} recipient(s).` });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={list ? "Edit email list" : "New email list"}
        description="Recipients are emailed when an alert fires or a resource's health becomes critical (or warning) in the chosen scope."
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              disabled={!canSave || mutation.isPending}
              onClick={() => {
                setTouched(true);
                if (canSave) mutation.mutate();
              }}
            >
              {list ? "Save changes" : "Create list"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Name" htmlFor="email-list-name">
            <Input id="email-list-name" value={name} maxLength={200} placeholder="Platform on-call" onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field
            label="Recipients"
            htmlFor="email-list-recipients"
            error={recipientError}
            hint={`One address per line (or separated by commas). ${valid.length} of up to ${MAX_RECIPIENTS}. Recipients are sent each email in BCC and do not see each other.`}
          >
            <Textarea
              id="email-list-recipients"
              rows={5}
              value={recipientsText}
              placeholder={"ops@contoso.com\nlead@contoso.com"}
              aria-invalid={recipientError ? true : undefined}
              onBlur={() => setTouched(true)}
              onChange={(e) => setRecipientsText(e.target.value)}
            />
          </Field>
          <Field label="Email when" htmlFor="email-list-severity">
            <Select id="email-list-severity" value={severity} onChange={(e) => setSeverity(e.target.value as EmailList["min_severity"])}>
              <option value="critical">Critical issues only</option>
              <option value="warning">Critical issues and warnings</option>
            </Select>
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Project" htmlFor="email-list-project">
              <Select
                id="email-list-project"
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
            <Field label="Environment" htmlFor="email-list-environment">
              <Select id="email-list-environment" value={environmentId} disabled={!project} onChange={(e) => setEnvironmentId(e.target.value)}>
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
              Also email when an alert resolves or a resource recovers
              <span className="block text-xs text-muted-foreground">Recommended, so recipients know when no action is needed any more.</span>
            </span>
          </label>
          <div className="flex items-center gap-2">
            <Switch id="email-list-enabled" checked={enabled} onCheckedChange={setEnabled} />
            <Label htmlFor="email-list-enabled">Enabled</Label>
          </div>
          {mutation.isError ? <ErrorState error={mutation.error} compact /> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

const VISIBLE_RECIPIENTS = 6;

function Recipients({ addresses }: { addresses: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? addresses : addresses.slice(0, VISIBLE_RECIPIENTS);
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Recipients">
      {shown.map((a) => (
        <li key={a} className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-xs">
          {a}
        </li>
      ))}
      {addresses.length > VISIBLE_RECIPIENTS ? (
        <li>
          <button type="button" className="px-1 text-xs text-primary hover:underline" onClick={() => setExpanded((v) => !v)}>
            {expanded ? "Show fewer" : `+${addresses.length - VISIBLE_RECIPIENTS} more`}
          </button>
        </li>
      ) : null}
    </ul>
  );
}

function EmailListRow({ list, onEdit }: { list: EmailList; onEdit: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => endpoints.updateEmailList(list.id, { enabled }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["email-lists"] }),
    onError: () => notify({ tone: "warning", title: "Could not change the list", description: "Try again." }),
  });
  const test = useMutation({
    mutationFn: () => endpoints.testEmailList(list.id),
    onSuccess: (result) =>
      notify(
        result.status === "sent"
          ? { tone: "success", title: "Test email sent", description: result.message }
          : { tone: "warning", title: "Test email not sent", description: result.message },
      ),
    onError: () => notify({ tone: "warning", title: "Test email not sent", description: "The request failed. Try again." }),
  });
  return (
    <li className="space-y-3 px-5 py-4">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold">{list.name}</h3>
            <Badge tone={list.min_severity === "critical" ? "critical" : "warning"}>{SEVERITY_LABEL[list.min_severity]}</Badge>
            {!list.enabled ? <Badge tone="neutral">Disabled</Badge> : null}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {scopeLabel(list)} · {list.recipients.length} recipient{list.recipients.length === 1 ? "" : "s"} ·{" "}
            {list.notify_resolved ? "emails recoveries" : "no recovery emails"}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <div className="mr-1 flex items-center gap-2">
            <Switch
              id={`email-list-${list.id}-enabled`}
              checked={list.enabled}
              disabled={toggle.isPending}
              aria-label={`${list.enabled ? "Disable" : "Enable"} ${list.name}`}
              onCheckedChange={(v) => toggle.mutate(v)}
            />
          </div>
          <Button variant="outline" size="sm" disabled={test.isPending || !list.enabled} onClick={() => test.mutate()}>
            <Send /> {test.isPending ? "Sending..." : "Send test email"}
          </Button>
          <Button variant="outline" size="sm" onClick={onEdit} aria-label={`Edit ${list.name}`}>
            <Pencil /> Edit
          </Button>
          <ConfirmButton
            title={`Delete "${list.name}"?`}
            description="Its recipients will stop receiving alert emails. Alert rules and history are not affected."
            confirmLabel="Delete list"
            onConfirm={async () => {
              await endpoints.deleteEmailList(list.id);
              await qc.invalidateQueries({ queryKey: ["email-lists"] });
            }}
          >
            <Trash2 /> Delete
          </ConfirmButton>
        </div>
      </div>
      <Recipients addresses={list.recipients} />
    </li>
  );
}

export function EmailNotifications() {
  const status = useQuery({ queryKey: ["email-status"], queryFn: endpoints.emailStatus, staleTime: 5 * 60_000 });
  const lists = useQuery({ queryKey: ["email-lists"], queryFn: endpoints.emailLists });
  const [editing, setEditing] = useState<EmailList | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const openDialog = (list: EmailList | null) => {
    setEditing(list);
    setDialogOpen(true);
  };

  return (
    <div className="space-y-4">
      {status.data && !status.data.configured ? (
        <div role="status" className="flex gap-3 rounded-lg border border-warning/30 bg-warning/5 px-5 py-3 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
          <div>
            <p className="font-medium">Email delivery is not set up in this deployment</p>
            <p className="text-muted-foreground">
              You can create lists now; nothing is sent until an administrator configures Azure Communication Services (EMAIL_PROVIDER=acs).
            </p>
          </div>
        </div>
      ) : status.data?.provider === "log" ? (
        <div role="status" className="flex gap-3 rounded-lg border border-border bg-muted/40 px-5 py-3 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden="true" />
          <p className="text-muted-foreground">Development mode: emails are written to the API log instead of being sent.</p>
        </div>
      ) : null}

      <Card>
        <CardHeader
          title="Email notifications"
          description="Who is emailed when something goes wrong. Each list receives every alert and every change to critical (or warning) in its scope, and optionally recoveries."
          actions={
            <Button size="sm" onClick={() => openDialog(null)}>
              <Plus /> New email list
            </Button>
          }
        />
        {lists.isLoading ? (
          <CardContent>
            <LoadingBlock label="Loading email lists" />
          </CardContent>
        ) : lists.isError ? (
          <CardContent>
            <ErrorState error={lists.error} title="Unable to load email lists." onRetry={() => void lists.refetch()} />
          </CardContent>
        ) : (lists.data ?? []).length === 0 ? (
          <EmptyState
            icon={<Mail className="size-10" />}
            title="No email lists yet"
            description="Create a list, for example 'Platform on-call', and add the people who should be emailed about critical issues."
            action={
              <Button onClick={() => openDialog(null)}>
                <Plus /> New email list
              </Button>
            }
          />
        ) : (
          <ul className="divide-y divide-border/70 border-t border-border/70">
            {lists.data?.map((list) => (
              <EmailListRow key={list.id} list={list} onEdit={() => openDialog(list)} />
            ))}
          </ul>
        )}
      </Card>
      {dialogOpen ? <EmailListDialog key={editing?.id ?? "new"} list={editing} open={dialogOpen} onOpenChange={setDialogOpen} /> : null}
    </div>
  );
}
