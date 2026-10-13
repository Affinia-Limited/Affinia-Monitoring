import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Pencil, Plus, RotateCcw, Search, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/client";
import { endpoints } from "@/api/endpoints";
import { ConfirmButton } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Label, Select, Switch } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { useDebounce } from "@/hooks/useDebounce";
import { useAccess } from "@/hooks/useAccess";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { AlertTemplate, AlertTemplateAssignment, AlertTemplateAssignmentIn, Resource, TemplateRule, TemplateRuleOverride } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatValue } from "@/utils/format";
import { EvaluateNowButton } from "./EvaluateNowButton";
import {
  formatMinutes,
  OPERATOR_WORD,
  overridesError,
  parseThreshold,
  RuleOverridesTable,
  SCOPE_KIND,
  scopeLabel,
  thresholdText,
  TIER_LABEL,
  tierOrderError,
  TIERS,
  TierValue,
  type Tier,
} from "./templateShared";

function invalidateTemplates(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["alert-templates"] });
  void qc.invalidateQueries({ queryKey: ["alert-template"] });
  void qc.invalidateQueries({ queryKey: ["alert-template-assignments"] });
  void qc.invalidateQueries({ queryKey: ["alert-plan"] });
}

// ---------------------------------------------------------------- notification channels

function ChannelPicker({ value, onChange }: { value: string[]; onChange: (next: string[]) => void }) {
  const channels = useQuery({ queryKey: ["channels"], queryFn: endpoints.channels });
  const options = (channels.data ?? []).filter((c) => c.channel_type !== "email");
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Also notify (optional)</legend>
      <p className="text-xs text-muted-foreground">
        Microsoft Teams channels and email lists set up under their own tabs already receive warnings and critical alerts. Choose channels here only
        for extra destinations.
      </p>
      {options.length === 0 ? (
        <p className="text-xs text-muted-foreground">No other notification channels exist.</p>
      ) : (
        <ul className="space-y-1">
          {options.map((c) => (
            <li key={c.id}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={value.includes(c.id)}
                  onChange={(e) => onChange(e.target.checked ? [...value, c.id] : value.filter((id) => id !== c.id))}
                />
                {c.name} <span className="text-xs text-muted-foreground">({c.channel_type})</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}

// ---------------------------------------------------------------- apply dialog

type ScopeChoice = "resource" | "environment" | "project" | "organization";
const SCOPE_CHOICES: { value: ScopeChoice; label: string }[] = [
  { value: "resource", label: "One resource" },
  { value: "environment", label: "Environment" },
  { value: "project", label: "Project" },
  { value: "organization", label: "Everything" },
];

function ResourcePicker({ selected, onSelect }: { selected: Resource | null; onSelect: (r: Resource | null) => void }) {
  const [text, setText] = useState("");
  const q = useDebounce(text.trim(), 300);
  const results = useQuery({
    queryKey: ["resources", { q, monitored_only: true, page_size: 8, picker: true }],
    queryFn: () => endpoints.resources({ q: q || undefined, monitored_only: true, page_size: 8, sort: "name" }),
    placeholderData: keepPreviousData,
  });
  if (selected) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{selected.name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {selected.type_display_name}
            {selected.project_name ? ` · ${selected.project_name} / ${selected.environment_name ?? "-"}` : " · Unassigned"}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => onSelect(null)}>
          Change
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input aria-label="Search resources" placeholder="Search by name, e.g. app-crm-prod" className="pl-8" value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <ul className="max-h-56 divide-y divide-border/70 overflow-y-auto rounded-md border border-border" aria-label="Matching resources">
        {(results.data?.items ?? []).map((r) => (
          <li key={r.id}>
            <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-muted" onClick={() => onSelect(r)}>
              <span className="block truncate font-medium">{r.name}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {r.type_display_name}
                {r.project_name ? ` · ${r.project_name} / ${r.environment_name ?? "-"}` : ""}
              </span>
            </button>
          </li>
        ))}
        {results.data && results.data.items.length === 0 ? <li className="px-3 py-2 text-sm text-muted-foreground">No monitored resources match.</li> : null}
      </ul>
    </div>
  );
}

function CoveredTypes({ templates }: { templates: AlertTemplate[] }) {
  const relevant = templates.filter((t) => t.resource_count > 0);
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Resource types that will be covered</p>
      {relevant.length === 0 ? (
        <p className="text-sm text-muted-foreground">No monitored resources with a template were found yet.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {relevant.map((t) => (
            <li key={t.monitor_key} className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-1.5 text-sm">
              <span className="truncate">{t.display_name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {t.rules.length} alert{t.rules.length === 1 ? "" : "s"} · {t.resource_count} resource{t.resource_count === 1 ? "" : "s"}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        Resources discovered later are covered automatically. Where several coverages apply to a resource, the most specific one wins (resource, then
        environment, then project, then everything).
      </p>
    </div>
  );
}

export function ApplyTemplatesDialog({
  open,
  onOpenChange,
  initial,
  onEditExisting,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-selected scope, e.g. from a resource or environment page. */
  initial?: { scope: ScopeChoice; resource?: Resource | null; projectId?: string; environmentId?: string };
  onEditExisting?: (assignmentId: string) => void;
}) {
  const qc = useQueryClient();
  const { unrestricted } = useAccess();
  const { notify } = useToast();
  const [scope, setScope] = useState<ScopeChoice>(initial?.scope ?? "resource");
  const [resource, setResource] = useState<Resource | null>(initial?.resource ?? null);
  const [projectId, setProjectId] = useState(initial?.projectId ?? "");
  const [environmentId, setEnvironmentId] = useState(initial?.environmentId ?? "");
  const [overrides, setOverrides] = useState<Record<string, TemplateRuleOverride>>({});
  const [channelIds, setChannelIds] = useState<string[]>([]);
  const [existingId, setExistingId] = useState<string | null>(null);
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, enabled: open });
  const templates = useQuery({ queryKey: ["alert-templates"], queryFn: endpoints.alertTemplates, enabled: open });
  const monitorKey = scope === "resource" ? resource?.monitor_key : null;
  const template = useQuery({
    queryKey: ["alert-template", monitorKey],
    queryFn: () => endpoints.alertTemplate(monitorKey as string),
    enabled: open && !!monitorKey,
    retry: false,
  });
  const project = projects.data?.find((p) => p.id === projectId);

  const scopeReady =
    scope === "organization" ||
    (scope === "project" && !!projectId) ||
    (scope === "environment" && !!projectId && !!environmentId) ||
    (scope === "resource" && !!resource && !!template.data);
  const validation = scope === "resource" && template.data ? overridesError([template.data], overrides) : null;

  const create = useMutation({
    mutationFn: () => {
      const body: AlertTemplateAssignmentIn = { notification_channel_ids: channelIds };
      if (scope === "resource" && resource) {
        body.resource_id = resource.id;
        if (Object.keys(overrides).length) body.overrides = overrides;
      }
      if (scope === "project" || scope === "environment") body.project_id = projectId;
      if (scope === "environment") body.environment_id = environmentId;
      return endpoints.createTemplateAssignment(body);
    },
    onSuccess: (created) => {
      invalidateTemplates(qc);
      notify({
        tone: "success",
        title: "Recommended alerts applied",
        description: `${scopeLabel(created)}: ${created.covered_resources} resource${created.covered_resources === 1 ? "" : "s"} covered. Alerts start at the next check.`,
      });
      onOpenChange(false);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "ASSIGNMENT_EXISTS") {
        const id = typeof error.details?.id === "string" ? error.details.id : null;
        setExistingId(id);
      }
    },
  });
  const exists = create.error instanceof ApiError && create.error.code === "ASSIGNMENT_EXISTS";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Apply recommended alerts"
        description="Choose what to cover. Each resource gets the ready-made alerts for its type, with Info, Warning and Critical levels, evaluation window and frequency already set."
        className="max-w-3xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button disabled={!scopeReady || !!validation || create.isPending} onClick={() => create.mutate()}>
              Apply recommended alerts
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div role="radiogroup" aria-label="Coverage" className="inline-flex flex-wrap rounded-md bg-muted p-0.5 text-sm">
            {SCOPE_CHOICES.filter((c) => c.value !== "organization" || unrestricted).map((c) => (
              <button
                key={c.value}
                type="button"
                role="radio"
                aria-checked={scope === c.value}
                onClick={() => {
                  setScope(c.value);
                  create.reset();
                }}
                className={cn("rounded px-3 py-1.5 font-medium text-muted-foreground transition-colors", scope === c.value && "bg-card text-foreground shadow-sm")}
              >
                {c.label}
              </button>
            ))}
          </div>

          {scope === "resource" ? (
            <div className="space-y-3">
              <ResourcePicker
                selected={resource}
                onSelect={(r) => {
                  setResource(r);
                  setOverrides({});
                  create.reset();
                }}
              />
              {resource && template.isLoading ? <LoadingBlock label="Loading the template" /> : null}
              {resource && template.isError ? (
                <p className="text-sm text-muted-foreground">There is no alert template for this resource type yet.</p>
              ) : null}
              {template.data ? (
                <div className="space-y-2">
                  <p className="text-sm">
                    <span className="font-medium">{template.data.display_name}</span>{" "}
                    <span className="text-muted-foreground">
                      template: {template.data.rules.length} alerts. Adjust a value to change it for this resource only.
                    </span>
                  </p>
                  <RuleOverridesTable template={template.data} overrides={overrides} onChange={setOverrides} editable />
                </div>
              ) : null}
            </div>
          ) : (
            <div className="space-y-3">
              {scope !== "organization" ? (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label="Project" htmlFor="apply-project">
                    <Select
                      id="apply-project"
                      value={projectId}
                      onChange={(e) => {
                        setProjectId(e.target.value);
                        setEnvironmentId("");
                        create.reset();
                      }}
                    >
                      <option value="">Choose a project</option>
                      {projects.data?.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {scope === "environment" ? (
                    <Field label="Environment" htmlFor="apply-environment">
                      <Select
                        id="apply-environment"
                        value={environmentId}
                        disabled={!project}
                        onChange={(e) => {
                          setEnvironmentId(e.target.value);
                          create.reset();
                        }}
                      >
                        <option value="">Choose an environment</option>
                        {project?.environments.map((env) => (
                          <option key={env.id} value={env.id}>
                            {env.name}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  ) : null}
                </div>
              ) : null}
              <CoveredTypes templates={templates.data ?? []} />
            </div>
          )}

          <ChannelPicker value={channelIds} onChange={setChannelIds} />

          {validation ? (
            <p role="alert" className="text-sm text-critical">
              {validation}
            </p>
          ) : null}
          {exists ? (
            <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-sm">
              <span>This is already covered. Edit the existing coverage instead of adding another.</span>
              {existingId && onEditExisting ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    onOpenChange(false);
                    onEditExisting(existingId);
                  }}
                >
                  Edit the existing coverage
                </Button>
              ) : null}
            </div>
          ) : create.isError ? (
            <ErrorState error={create.error} compact />
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- customise an assignment

export function CustomiseAssignmentDialog({
  assignment,
  open,
  onOpenChange,
  monitorKey,
}: {
  assignment: AlertTemplateAssignment;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The resource's type when the assignment covers one resource. */
  monitorKey?: string | null;
}) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const all = useQuery({ queryKey: ["alert-templates"], queryFn: endpoints.alertTemplates, enabled: open });
  const [overrides, setOverrides] = useState<Record<string, TemplateRuleOverride>>(assignment.overrides ?? {});
  const [channelIds, setChannelIds] = useState<string[]>(assignment.notification_channel_ids ?? []);
  const relevant = (all.data ?? []).filter((t) =>
    monitorKey ? t.monitor_key === monitorKey : assignment.templates.includes(t.monitor_key) || Object.keys(overrides).some((k) => k.startsWith(`${t.monitor_key}:`)),
  );
  const validation = overridesError(relevant, overrides);
  const save = useMutation({
    mutationFn: () => endpoints.updateTemplateAssignment(assignment.id, { overrides, notification_channel_ids: channelIds }),
    onSuccess: () => {
      invalidateTemplates(qc);
      notify({ tone: "success", title: "Coverage saved", description: `${scopeLabel(assignment)}: changes apply at the next check.` });
      onOpenChange(false);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={`Customise: ${scopeLabel(assignment)}`}
        description="Values you change here apply only to the resources this coverage covers. Everything else follows the template."
        className="max-w-3xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            {canManage ? (
              <Button disabled={!!validation || save.isPending} onClick={() => save.mutate()}>
                Save changes
              </Button>
            ) : null}
          </>
        }
      >
        <div className="space-y-4">
          {all.isLoading ? <LoadingBlock label="Loading templates" /> : null}
          {relevant.map((t) => (
            <section key={t.monitor_key} aria-label={t.display_name} className="space-y-2">
              <h3 className="text-sm font-semibold">{t.display_name}</h3>
              <RuleOverridesTable template={t} overrides={overrides} onChange={setOverrides} editable={canManage} />
            </section>
          ))}
          {!all.isLoading && relevant.length === 0 ? <p className="text-sm text-muted-foreground">No resources with a template are covered yet.</p> : null}
          {canManage ? <ChannelPicker value={channelIds} onChange={setChannelIds} /> : null}
          {validation ? (
            <p role="alert" className="text-sm text-critical">
              {validation}
            </p>
          ) : null}
          {save.isError ? <ErrorState error={save.error} compact /> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- coverage list

function AssignmentRow({ assignment, onCustomise }: { assignment: AlertTemplateAssignment; onCustomise: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => endpoints.updateTemplateAssignment(assignment.id, { enabled }),
    onSuccess: () => invalidateTemplates(qc),
    onError: () => notify({ tone: "warning", title: "Could not change the coverage", description: "Try again." }),
  });
  const customised = Object.keys(assignment.overrides ?? {}).length;
  // ``templates`` holds resource-type keys; show their friendly names (same cached query as the Templates card).
  const catalogue = useQuery({ queryKey: ["alert-templates"], queryFn: endpoints.alertTemplates, staleTime: 60_000 });
  const typeNames = assignment.templates.map((key) => catalogue.data?.find((t) => t.monitor_key === key)?.display_name ?? key);
  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-2 px-5 py-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold">{scopeLabel(assignment)}</h3>
          <Badge tone="outline">{SCOPE_KIND[assignment.scope]}</Badge>
          {!assignment.enabled ? <Badge tone="neutral">Off</Badge> : null}
          {customised ? <Badge tone="info">{customised} customised</Badge> : null}
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {assignment.enabled
            ? `${assignment.covered_resources} resource${assignment.covered_resources === 1 ? "" : "s"} covered`
            : "Recommended alerts turned off here"}
          {typeNames.length ? ` · ${typeNames.join(", ")}` : ""}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Switch
          checked={assignment.enabled}
          disabled={!canManage || toggle.isPending}
          aria-label={`${assignment.enabled ? "Turn off" : "Turn on"} recommended alerts for ${scopeLabel(assignment)}`}
          onCheckedChange={(v) => toggle.mutate(v)}
        />
        <Button variant="outline" size="sm" onClick={onCustomise} aria-label={`Customise ${scopeLabel(assignment)}`}>
          <Pencil /> {canManage ? "Customise" : "View"}
        </Button>
        {canManage ? (
          <ConfirmButton
            title={`Remove coverage for "${scopeLabel(assignment)}"?`}
            description="Its resources stop getting recommended alerts unless a broader coverage still applies. Open alerts from it are resolved."
            confirmLabel="Remove coverage"
            onConfirm={async () => {
              await endpoints.deleteTemplateAssignment(assignment.id);
              invalidateTemplates(qc);
            }}
          >
            <Trash2 /> Remove
          </ConfirmButton>
        ) : null}
      </div>
    </li>
  );
}

function CoverageCard() {
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const assignments = useQuery({ queryKey: ["alert-template-assignments"], queryFn: () => endpoints.templateAssignments() });
  const [applyOpen, setApplyOpen] = useState(false);
  const [customising, setCustomising] = useState<string | null>(null);
  const editing = assignments.data?.find((a) => a.id === customising) ?? null;
  return (
    <Card>
      <CardHeader
        title="Coverage"
        description="Applying templates turns on the recommended alerts for every resource in the scope, automatically."
        actions={
          canManage ? (
            <>
              <EvaluateNowButton />
              <Button size="sm" onClick={() => setApplyOpen(true)}>
                <Plus /> Apply recommended alerts
              </Button>
            </>
          ) : null
        }
      />
      {assignments.isLoading ? (
        <CardContent>
          <LoadingBlock label="Loading coverage" />
        </CardContent>
      ) : assignments.isError ? (
        <CardContent>
          <ErrorState error={assignments.error} title="Unable to load coverage." onRetry={() => void assignments.refetch()} />
        </CardContent>
      ) : (assignments.data ?? []).length === 0 ? (
        <EmptyState
          icon={<ShieldCheck className="size-10" />}
          title="No recommended alerts yet"
          description="Apply the recommended alerts to everything, a project, an environment or one resource. Each resource gets the ready-made alerts for its type."
          action={
            canManage ? (
              <Button onClick={() => setApplyOpen(true)}>
                <Plus /> Apply recommended alerts
              </Button>
            ) : null
          }
        />
      ) : (
        <ul className="divide-y divide-border/70 border-t border-border/70">
          {assignments.data?.map((a) => (
            <AssignmentRow key={a.id} assignment={a} onCustomise={() => setCustomising(a.id)} />
          ))}
        </ul>
      )}
      {applyOpen ? <ApplyTemplatesDialog open={applyOpen} onOpenChange={setApplyOpen} onEditExisting={setCustomising} /> : null}
      {editing ? (
        <CustomiseAssignmentDialog
          key={editing.id}
          assignment={editing}
          open={!!editing}
          onOpenChange={(o) => {
            if (!o) setCustomising(null);
          }}
        />
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------- template rules

function RuleEditDialog({ template, rule, open, onOpenChange }: { template: AlertTemplate; rule: TemplateRule; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [values, setValues] = useState<Record<Tier, string>>({ info: thresholdText(rule.info), warning: thresholdText(rule.warning), critical: thresholdText(rule.critical) });
  const [windowMinutes, setWindowMinutes] = useState(String(rule.window_minutes));
  const [enabled, setEnabled] = useState(rule.enabled);
  const parsed = { info: parseThreshold(values.info), warning: parseThreshold(values.warning), critical: parseThreshold(values.critical) };
  const window = Number(windowMinutes);
  const clientError = !enabled
    ? null
    : TIERS.some((t) => parsed[t] !== null && Number.isNaN(parsed[t]))
      ? "Enter numbers only."
      : !Number.isInteger(window) || window < 1 || window > 1440
        ? "The window must be a whole number of minutes between 1 and 1440."
        : tierOrderError(rule.operator, parsed);
  const save = useMutation({
    mutationFn: () => endpoints.updateTemplateRule(template.monitor_key, rule.metric, { enabled, ...parsed, window_minutes: window }),
    onSuccess: () => {
      invalidateTemplates(qc);
      notify({ tone: "success", title: "Template updated", description: `${template.display_name}: ${rule.label}. Applies at the next check.` });
      onOpenChange(false);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={`${template.display_name}: ${rule.label}`}
        description={`Alert when ${rule.label} is ${OPERATOR_WORD[rule.operator]} a level${rule.unit ? ` (${rule.unit})` : ""}, over the window. Applies to every covered ${template.display_name} unless a coverage customises it.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button disabled={!!clientError || save.isPending} onClick={() => save.mutate()}>
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {TIERS.map((t) => (
              <Field
                key={t}
                label={TIER_LABEL[t]}
                htmlFor={`tier-${t}`}
                hint={`Recommended: ${rule[`default_${t}` as const] === null ? "none" : formatValue(rule[`default_${t}` as const], rule.unit)}`}
              >
                <Input id={`tier-${t}`} type="number" step="any" value={values[t]} disabled={!enabled} onChange={(e) => setValues({ ...values, [t]: e.target.value })} />
              </Field>
            ))}
          </div>
          <Field label="Window (minutes)" htmlFor="tier-window" hint={`Recommended: ${formatMinutes(rule.default_window_minutes)}. Checked every ${formatMinutes(rule.frequency_minutes)}.`}>
            <Input id="tier-window" type="number" min={1} max={1440} value={windowMinutes} disabled={!enabled} onChange={(e) => setWindowMinutes(e.target.value)} />
          </Field>
          <div className="flex items-center gap-2">
            <Switch id="tier-enabled" checked={enabled} onCheckedChange={setEnabled} />
            <Label htmlFor="tier-enabled">Alert on</Label>
          </div>
          <p className="text-xs text-muted-foreground">Leave a level empty to skip it. Info alerts are recorded but do not notify Teams or email by default.</p>
          {clientError ? (
            <p role="alert" className="text-sm text-critical">
              {clientError}
            </p>
          ) : null}
          {save.isError ? <ErrorState error={save.error} compact /> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TemplateSection({ template, defaultOpen }: { template: AlertTemplate; defaultOpen: boolean }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  // Template defaults apply to the whole organisation, so only users with access to all projects edit them.
  const { unrestricted } = useAccess();
  const canManage = usePermission(PERMISSIONS.manageAlerts) && unrestricted;
  const [open, setOpen] = useState(defaultOpen);
  const [editing, setEditing] = useState<TemplateRule | null>(null);
  const reset = useMutation({
    mutationFn: (metric: string) => endpoints.resetTemplateRule(template.monitor_key, metric),
    onSuccess: () => {
      invalidateTemplates(qc);
      notify({ tone: "success", title: "Reset to recommended", description: template.display_name });
    },
    onError: (error) => notify({ tone: "warning", title: "Could not reset", description: error instanceof Error ? error.message : "Try again." }),
  });
  return (
    <section aria-label={template.display_name} className="border-t border-border/70">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-muted/40">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{template.display_name}</span>
            <span className="text-xs text-muted-foreground">{template.category}</span>
            {template.customized ? <Badge tone="info">Customised</Badge> : null}
          </div>
          <p className="text-xs text-muted-foreground">
            {template.rules.length} alert{template.rules.length === 1 ? "" : "s"} · {template.resource_count} resource{template.resource_count === 1 ? "" : "s"},{" "}
            {template.covered_count} covered
          </p>
        </div>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden="true" />
      </button>
      {open ? (
        <div className="overflow-x-auto pb-2">
          {template.description ? <p className="px-5 pb-2 text-xs text-muted-foreground">{template.description}</p> : null}
          <Table>
            <THead>
              <TR>
                <TH>Metric</TH>
                <TH>Condition</TH>
                {TIERS.map((t) => (
                  <TH key={t}>{TIER_LABEL[t]}</TH>
                ))}
                <TH>Window</TH>
                <TH>Every</TH>
                <TH>Enabled</TH>
                {canManage ? (
                  <TH className="text-right">
                    <span className="sr-only">Actions</span>
                  </TH>
                ) : null}
              </TR>
            </THead>
            <tbody>
              {template.rules.map((r) => (
                <TR key={r.metric} className={cn(!r.enabled && "opacity-60")}>
                  <TD>
                    <div className="font-medium">{r.label}</div>
                    {r.customized ? <div className="text-xs text-link">Customised</div> : null}
                  </TD>
                  <TD className="whitespace-nowrap text-muted-foreground">{OPERATOR_WORD[r.operator]}</TD>
                  {TIERS.map((t) => (
                    <TD key={t}>
                      <TierValue tier={t} value={r[t]} unit={r.unit} />
                    </TD>
                  ))}
                  <TD className="whitespace-nowrap text-muted-foreground">{formatMinutes(r.window_minutes)}</TD>
                  <TD className="whitespace-nowrap text-muted-foreground">{formatMinutes(r.frequency_minutes)}</TD>
                  <TD>{r.enabled ? "Yes" : "No"}</TD>
                  {canManage ? (
                    <TD className="text-right whitespace-nowrap">
                      <Button variant="ghost" size="sm" onClick={() => setEditing(r)} aria-label={`Edit ${template.display_name} ${r.label}`}>
                        <Pencil /> Edit
                      </Button>
                      {r.customized ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={reset.isPending}
                          onClick={() => reset.mutate(r.metric)}
                          aria-label={`Reset ${template.display_name} ${r.label} to recommended`}
                        >
                          <RotateCcw /> Reset to recommended
                        </Button>
                      ) : null}
                    </TD>
                  ) : null}
                </TR>
              ))}
            </tbody>
          </Table>
        </div>
      ) : null}
      {editing ? (
        <RuleEditDialog
          key={editing.metric}
          template={template}
          rule={editing}
          open={!!editing}
          onOpenChange={(o) => {
            if (!o) setEditing(null);
          }}
        />
      ) : null}
    </section>
  );
}

function TemplatesCard() {
  const templates = useQuery({ queryKey: ["alert-templates"], queryFn: endpoints.alertTemplates });
  const sorted = [...(templates.data ?? [])].sort((a, b) => b.resource_count - a.resource_count || a.display_name.localeCompare(b.display_name));
  return (
    <Card>
      <CardHeader
        title="Templates"
        description="The ready-made alerts for each supported resource type. Info means keep an eye on it, Warning may need attention, Critical needs immediate action."
      />
      {templates.isLoading ? (
        <CardContent>
          <LoadingBlock label="Loading templates" />
        </CardContent>
      ) : templates.isError ? (
        <CardContent>
          <ErrorState error={templates.error} title="Unable to load templates." onRetry={() => void templates.refetch()} />
        </CardContent>
      ) : (
        <div>
          {sorted.map((t, i) => (
            <TemplateSection key={t.monitor_key} template={t} defaultOpen={i === 0 && t.resource_count > 0} />
          ))}
        </div>
      )}
    </Card>
  );
}

export function AlertTemplates() {
  return (
    <div className="space-y-4">
      <CoverageCard />
      <TemplatesCard />
    </div>
  );
}
