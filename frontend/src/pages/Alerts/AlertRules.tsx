import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { endpoints } from "@/api/endpoints";
import { ConfirmButton } from "@/components/common";
import { SeverityBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Switch, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { AlertRule, AlertRuleIn, Operator, Severity } from "@/types/api";

const OPERATORS: { value: Operator; label: string }[] = [
  { value: "gt", label: "Greater than" },
  { value: "gte", label: "Greater than or equal" },
  { value: "lt", label: "Less than" },
  { value: "lte", label: "Less than or equal" },
];
const OP_SYMBOL: Record<string, string> = { gt: ">", gte: ">=", lt: "<", lte: "<=" };

const EMPTY: AlertRuleIn = {
  name: "",
  description: "",
  enabled: true,
  monitor_key: "app_service",
  metric_name: "",
  aggregation: "Average",
  operator: "gt",
  threshold: 90,
  severity: "warning",
  window_minutes: 15,
  resource_id: null,
  project_id: null,
  environment_id: null,
  notification_channel_ids: [],
};

function RuleDialog({ rule, open, onOpenChange }: { rule: AlertRule | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const monitors = useQuery({ queryKey: ["monitors"], queryFn: endpoints.monitors });
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects });
  const channels = useQuery({ queryKey: ["channels"], queryFn: endpoints.channels });
  const [form, setForm] = useState<AlertRuleIn>(rule ? { ...rule } : EMPTY);
  const resources = useQuery({
    queryKey: ["resources", { monitor_key: form.monitor_key, project_id: form.project_id, rules: true }],
    queryFn: () => endpoints.resources({ monitor_key: form.monitor_key, project_id: form.project_id, page_size: 200 }),
  });
  const monitor = monitors.data?.find((m) => m.key === form.monitor_key);
  const project = projects.data?.find((p) => p.id === form.project_id);
  const set = <K extends keyof AlertRuleIn>(key: K, value: AlertRuleIn[K]) => setForm((f) => ({ ...f, [key]: value }));
  const mutation = useMutation({
    mutationFn: () => (rule ? endpoints.updateAlertRule(rule.id, form) : endpoints.createAlertRule(form)),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["alert-rules"] });
      onOpenChange(false);
    },
  });
  const valid = form.name.trim() && form.metric_name && Number.isFinite(form.threshold);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={rule ? "Edit alert rule" : "New alert rule"}
        description="Rules are evaluated by the platform every few minutes against Azure Monitor metrics."
        className="max-w-2xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button disabled={!valid || mutation.isPending} onClick={() => mutation.mutate()}>
              {rule ? "Save rule" : "Create rule"}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="rule-name" className="sm:col-span-2">
            <Input id="rule-name" value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Resource type" htmlFor="rule-monitor">
            <Select
              id="rule-monitor"
              value={form.monitor_key}
              onChange={(e) => setForm((f) => ({ ...f, monitor_key: e.target.value, metric_name: "", resource_id: null }))}
            >
              {monitors.data
                ?.filter((m) => m.metrics.length > 0)
                .map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.display_name}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Metric" htmlFor="rule-metric">
            <Select
              id="rule-metric"
              value={form.metric_name}
              onChange={(e) => {
                const m = monitor?.metrics.find((x) => x.key === e.target.value);
                setForm((f) => ({ ...f, metric_name: e.target.value, aggregation: (m?.aggregation as AlertRuleIn["aggregation"]) ?? f.aggregation }));
              }}
            >
              <option value="">Select a metric</option>
              {monitor?.metrics.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label} ({m.unit})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Aggregation" htmlFor="rule-agg">
            <Select id="rule-agg" value={form.aggregation} onChange={(e) => set("aggregation", e.target.value as AlertRuleIn["aggregation"])}>
              {["Average", "Total", "Maximum", "Minimum", "Count"].map((a) => (
                <option key={a}>{a}</option>
              ))}
            </Select>
          </Field>
          <Field label="Window (minutes)" htmlFor="rule-window">
            <Input id="rule-window" type="number" min={5} max={1440} value={form.window_minutes} onChange={(e) => set("window_minutes", Number(e.target.value))} />
          </Field>
          <Field label="Operator" htmlFor="rule-op">
            <Select id="rule-op" value={form.operator} onChange={(e) => set("operator", e.target.value as Operator)}>
              {OPERATORS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Threshold" htmlFor="rule-threshold">
            <Input id="rule-threshold" type="number" step="any" value={form.threshold} onChange={(e) => set("threshold", Number(e.target.value))} />
          </Field>
          <Field label="Severity" htmlFor="rule-severity">
            <Select id="rule-severity" value={form.severity} onChange={(e) => set("severity", e.target.value as Severity)}>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </Select>
          </Field>
          <div className="flex items-center gap-2 pt-6">
            <Switch id="rule-enabled" checked={form.enabled} onCheckedChange={(c) => set("enabled", c)} />
            <label htmlFor="rule-enabled" className="text-sm">
              Enabled
            </label>
          </div>
          <Field label="Project scope" htmlFor="rule-project">
            <Select
              id="rule-project"
              value={form.project_id ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, project_id: e.target.value || null, environment_id: null, resource_id: null }))}
            >
              <option value="">All projects</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Environment scope" htmlFor="rule-env">
            <Select id="rule-env" value={form.environment_id ?? ""} disabled={!project} onChange={(e) => set("environment_id", e.target.value || null)}>
              <option value="">All environments</option>
              {project?.environments.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Single resource (optional)" htmlFor="rule-resource" className="sm:col-span-2">
            <Select id="rule-resource" value={form.resource_id ?? ""} onChange={(e) => set("resource_id", e.target.value || null)}>
              <option value="">Every matching resource</option>
              {resources.data?.items.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </Select>
          </Field>
          <fieldset className="sm:col-span-2">
            <legend className="mb-1.5 text-xs font-medium">Notification channels</legend>
            {(channels.data ?? []).length === 0 ? (
              <p className="text-xs text-muted-foreground">No channels configured.</p>
            ) : (
              <div className="flex flex-wrap gap-3">
                {channels.data?.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.notification_channel_ids.includes(c.id)}
                      onChange={(e) =>
                        set(
                          "notification_channel_ids",
                          e.target.checked ? [...form.notification_channel_ids, c.id] : form.notification_channel_ids.filter((x) => x !== c.id),
                        )
                      }
                    />
                    {c.name}
                  </label>
                ))}
              </div>
            )}
          </fieldset>
          <Field label="Description" htmlFor="rule-description" className="sm:col-span-2">
            <Textarea id="rule-description" rows={2} value={form.description ?? ""} onChange={(e) => set("description", e.target.value)} />
          </Field>
        </div>
        {mutation.isError ? <ErrorState error={mutation.error} className="mt-3" /> : null}
      </DialogContent>
    </Dialog>
  );
}

export function AlertRules() {
  const qc = useQueryClient();
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const rules = useQuery({ queryKey: ["alert-rules"], queryFn: endpoints.alertRules });
  const monitors = useQuery({ queryKey: ["monitors"], queryFn: endpoints.monitors });
  const [editing, setEditing] = useState<AlertRule | null>(null);
  const [open, setOpen] = useState(false);
  const labelFor = (monitorKey: string, metric: string) => {
    const m = monitors.data?.find((x) => x.key === monitorKey);
    return { monitor: m?.display_name ?? monitorKey, metric: m?.metrics.find((x) => x.key === metric)?.label ?? metric };
  };
  return (
    <Card>
      <CardHeader
        title="Alert rules"
        description="Metric conditions evaluated by the platform"
        actions={
          canManage ? (
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setOpen(true);
              }}
            >
              <Plus /> New rule
            </Button>
          ) : null
        }
      />
      <CardContent className="px-0">
        {rules.isLoading ? (
          <div className="px-4">
            <LoadingBlock />
          </div>
        ) : rules.isError ? (
          <div className="px-4">
            <ErrorState error={rules.error} />
          </div>
        ) : (rules.data ?? []).length === 0 ? (
          <EmptyState title="No alert rules" description="Create a rule to be alerted when a metric crosses a threshold." />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Resource type</TH>
                <TH>Condition</TH>
                <TH>Severity</TH>
                <TH>Status</TH>
                {canManage ? <TH className="text-right">Actions</TH> : null}
              </TR>
            </THead>
            <tbody>
              {rules.data?.map((r) => {
                const l = labelFor(r.monitor_key, r.metric_name);
                return (
                  <TR key={r.id}>
                    <TD className="font-medium">{r.name}</TD>
                    <TD>{l.monitor}</TD>
                    <TD className="tabular">
                      {r.aggregation} {l.metric} {OP_SYMBOL[r.operator]} {r.threshold} over {r.window_minutes} min
                    </TD>
                    <TD>
                      <SeverityBadge severity={r.severity} />
                    </TD>
                    <TD>{r.enabled ? <Badge tone="healthy">Enabled</Badge> : <Badge>Disabled</Badge>}</TD>
                    {canManage ? (
                      <TD className="text-right whitespace-nowrap">
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label={`Edit ${r.name}`}
                          onClick={() => {
                            setEditing(r);
                            setOpen(true);
                          }}
                        >
                          <Pencil />
                        </Button>
                        <ConfirmButton
                          title={`Delete rule ${r.name}?`}
                          description="Open alerts raised by this rule remain until resolved."
                          confirmLabel="Delete rule"
                          onConfirm={async () => {
                            await endpoints.deleteAlertRule(r.id);
                            await qc.invalidateQueries({ queryKey: ["alert-rules"] });
                          }}
                        >
                          <Trash2 />
                          <span className="sr-only">Delete {r.name}</span>
                        </ConfirmButton>
                      </TD>
                    ) : null}
                  </TR>
                );
              })}
            </tbody>
          </Table>
        )}
      </CardContent>
      {open ? <RuleDialog key={editing?.id ?? "new"} rule={editing} open={open} onOpenChange={setOpen} /> : null}
    </Card>
  );
}
