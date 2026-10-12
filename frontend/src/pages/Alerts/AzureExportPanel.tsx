import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, Copy, Download, FileCode2 } from "lucide-react";
import { useState } from "react";
import { type AzureAlertExport, type AzureAlertTemplate, deployCommand, exportAzureAlerts, parseRecipients } from "@/api/azureExport";
import { endpoints } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ErrorState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import { cn } from "@/utils/cn";

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
}

function download(t: AzureAlertTemplate): void {
  const blob = new Blob([JSON.stringify(t.template, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${t.filename}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function TemplateRow({ template }: { template: AzureAlertTemplate }) {
  const { notify } = useToast();
  const command = deployCommand(template);
  return (
    <li className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
      <FileCode2 className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{template.subscription_name}</p>
        <p className="truncate text-xs text-muted-foreground">
          {plural(template.alert_count, "alert rule")} · subscription {template.subscription_id}
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        aria-label={`Copy deploy command for ${template.subscription_name}`}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(command);
            notify({ title: "Deploy command copied", description: "Replace <your-resource-group> before running it.", tone: "success" });
          } catch {
            notify({ title: "Could not copy", description: command, tone: "warning" });
          }
        }}
      >
        <Copy /> Copy deploy command
      </Button>
      <Button size="sm" aria-label={`Download template for ${template.subscription_name}`} onClick={() => download(template)}>
        <Download /> Download {template.filename}.json
      </Button>
    </li>
  );
}

function Result({ result }: { result: AzureAlertExport }) {
  const [showSkipped, setShowSkipped] = useState(false);
  const total = result.templates.reduce((sum, t) => sum + t.alert_count, 0);
  if (result.templates.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        No alert rules apply to this scope. Choose a wider scope, or include health thresholds.
      </p>
    );
  }
  return (
    <div className="space-y-4" role="status">
      <p className="text-sm">
        <span className="font-medium">{plural(total, "alert rule")}</span> on {plural(result.resources, "resource")}, in{" "}
        {plural(result.templates.length, "template")} (one per Azure subscription).
      </p>
      <ul className="divide-y divide-border/70 rounded-lg border border-border">
        {result.templates.map((t) => (
          <TemplateRow key={t.subscription_id} template={t} />
        ))}
      </ul>
      {result.skipped.length ? (
        <div className="rounded-lg border border-warning/30 bg-warning/5">
          <button
            type="button"
            aria-expanded={showSkipped}
            onClick={() => setShowSkipped((v) => !v)}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm"
          >
            <span className="flex-1">{plural(result.skipped.length, "rule")} could not be exported as Azure metric alerts</span>
            <ChevronDown className={cn("size-4 transition-transform", showSkipped && "rotate-180")} aria-hidden="true" />
          </button>
          {showSkipped ? (
            <ul className="space-y-1.5 border-t border-warning/20 px-4 py-3 text-xs">
              {result.skipped.map((s, i) => (
                <li key={i}>
                  <span className="font-medium">{s.resource_name}</span> · {s.rule}: <span className="text-muted-foreground">{s.reason}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div className="space-y-1 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">Deploying a template</p>
        <p>
          Azure portal: Create a resource &gt; Template deployment (deploy using custom templates) &gt; Build your own template in the editor &gt; Load
          file, then choose a resource group in that subscription.
        </p>
        <p>
          Azure CLI: use the copied command. Check the changes first with <code>az deployment group what-if</code>. Deploying a newer export again updates
          the same alert rules in place.
        </p>
      </div>
    </div>
  );
}

/**
 * Generates Azure Monitor metric alerts (ARM templates) from the platform's health thresholds and custom
 * alert rules, with an email action group, so Azure evaluates and emails them natively.
 */
export function AzureExportPanel() {
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, enabled: canManage });
  const [projectId, setProjectId] = useState("");
  const [environmentId, setEnvironmentId] = useState("");
  const [includeHealth, setIncludeHealth] = useState(true);
  const [includeRules, setIncludeRules] = useState(true);
  const [recipients, setRecipients] = useState("");
  const [groupName, setGroupName] = useState("");
  const parsed = parseRecipients(recipients);
  const recipientError = parsed.invalid.length
    ? `${plural(parsed.invalid.length, "entry", "entries")} ${parsed.invalid.length === 1 ? "is" : "are"} not a valid email address: ${parsed.invalid.slice(0, 3).join(", ")}`
    : parsed.valid.length > 50
      ? "At most 50 recipients are supported."
      : null;
  const generate = useMutation({
    mutationFn: () =>
      exportAzureAlerts({
        project_id: projectId || null,
        environment_id: environmentId || null,
        include_health: includeHealth,
        include_rules: includeRules,
        recipients: parsed.valid.join(","),
        action_group_name: groupName.trim() || undefined,
      }),
  });
  if (!canManage) return null;
  const project = projects.data?.find((p) => p.id === projectId);
  const nothingSelected = !includeHealth && !includeRules;

  return (
    <Card>
      <CardHeader
        title="Export to Azure Monitor"
        description="Download your alert rules as ARM templates and deploy them to Azure, so Azure Monitor evaluates them and emails your team directly."
      />
      <CardContent className="space-y-5">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!recipientError && !nothingSelected) generate.mutate();
          }}
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Project" htmlFor="export-project">
              <Select
                id="export-project"
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
            <Field label="Environment" htmlFor="export-environment">
              <Select id="export-environment" value={environmentId} disabled={!project} onChange={(e) => setEnvironmentId(e.target.value)}>
                <option value="">All environments</option>
                {project?.environments.map((env) => (
                  <option key={env.id} value={env.id}>
                    {env.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-xs font-medium">Include</legend>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={includeHealth} onChange={(e) => setIncludeHealth(e.target.checked)} />
              Health thresholds (a warning and a critical alert per key metric, with your overrides)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={includeRules} onChange={(e) => setIncludeRules(e.target.checked)} />
              Custom alert rules
            </label>
            {nothingSelected ? (
              <p className="text-xs text-critical" role="alert">
                Choose at least one source.
              </p>
            ) : null}
          </fieldset>
          <Field
            label="Email recipients"
            htmlFor="export-recipients"
            error={recipientError}
            hint="Separate addresses with commas or new lines. Azure emails them whenever an exported alert fires or resolves. You can change them later in the Azure action group."
          >
            <Textarea id="export-recipients" rows={3} value={recipients} placeholder="ops@contoso.com, oncall@contoso.com" onChange={(e) => setRecipients(e.target.value)} />
          </Field>
          <Field label="Action group name (optional)" htmlFor="export-group" hint="Defaults to amp-alerts. Letters, digits, spaces, '.', '-' and '_'.">
            <Input id="export-group" value={groupName} maxLength={260} placeholder="amp-alerts" onChange={(e) => setGroupName(e.target.value)} />
          </Field>
          <Button type="submit" disabled={generate.isPending || !!recipientError || nothingSelected}>
            {generate.isPending ? "Generating..." : "Generate templates"}
          </Button>
        </form>
        {generate.isError ? <ErrorState error={generate.error} compact title="Unable to generate the templates." /> : null}
        {generate.data ? <Result result={generate.data} /> : null}
      </CardContent>
    </Card>
  );
}
