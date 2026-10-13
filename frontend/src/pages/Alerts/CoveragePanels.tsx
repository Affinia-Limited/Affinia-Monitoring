import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff, Pencil, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { ConfirmButton } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { AlertPlanRule, AlertTemplateAssignment, Resource } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatValue } from "@/utils/format";
import { ApplyTemplatesDialog, CustomiseAssignmentDialog } from "./AlertTemplates";
import { CurrentTierBadge, OPERATOR_WORD, SCOPE_KIND, scopeLabel, TIER_LABEL, TIERS, TierValue } from "./templateShared";

function useInvalidateCoverage() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["alert-plan"] });
    void qc.invalidateQueries({ queryKey: ["alert-template-assignments"] });
    void qc.invalidateQueries({ queryKey: ["alert-coverage-effective"] });
    void qc.invalidateQueries({ queryKey: ["alert-templates"] });
  };
}

function PlanTable({ rules, showCurrent }: { rules: AlertPlanRule[]; showCurrent: boolean }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <THead>
          <TR>
            <TH>Alert</TH>
            <TH>Condition</TH>
            {TIERS.map((t) => (
              <TH key={t}>{TIER_LABEL[t]}</TH>
            ))}
            {showCurrent ? (
              <>
                <TH>Now</TH>
                <TH>Status</TH>
              </>
            ) : null}
          </TR>
        </THead>
        <tbody>
          {rules.map((r) => (
            <TR key={r.metric} className={cn(!r.enabled && "opacity-60")}>
              <TD>
                <div className="font-medium">{r.label}</div>
                <div className="text-xs text-muted-foreground">
                  {r.enabled ? `${r.window_minutes} min window` : "Off"}
                  {r.overridden ? <span className="text-link"> · customised here</span> : null}
                </div>
              </TD>
              <TD className="whitespace-nowrap text-muted-foreground">{OPERATOR_WORD[r.operator]}</TD>
              {TIERS.map((t) => (
                <TD key={t}>
                  <TierValue tier={t} value={r[t]} unit={r.unit} />
                </TD>
              ))}
              {showCurrent ? (
                <>
                  <TD className="tabular whitespace-nowrap">{formatValue(r.current_value, r.unit)}</TD>
                  <TD>{r.enabled ? <CurrentTierBadge tier={r.current_tier} /> : <Badge tone="neutral">Off</Badge>}</TD>
                </>
              ) : null}
            </TR>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

/** Which recommended alerts apply to this resource, and how to change them. */
export function RecommendedAlertsPanel({ resource }: { resource: Resource }) {
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const invalidate = useInvalidateCoverage();
  const { notify } = useToast();
  const plan = useQuery({ queryKey: ["alert-plan", resource.id], queryFn: () => endpoints.alertPlan(resource.id) });
  const [applyOpen, setApplyOpen] = useState(false);
  const [customising, setCustomising] = useState<AlertTemplateAssignment | null>(null);
  const assignments = useQuery({
    queryKey: ["alert-template-assignments", { resource_id: resource.id }],
    queryFn: () => endpoints.templateAssignments({ resource_id: resource.id }),
    enabled: canManage,
  });
  const own = assignments.data?.find((a) => a.scope === "resource" && a.resource_id === resource.id) ?? null;

  const enable = useMutation({
    mutationFn: () => (own ? endpoints.updateTemplateAssignment(own.id, { enabled: true }) : endpoints.createTemplateAssignment({ resource_id: resource.id })),
    onSuccess: () => {
      invalidate();
      notify({ tone: "success", title: "Recommended alerts on", description: `${resource.name}: alerts start at the next check.` });
    },
  });
  const turnOff = async () => {
    if (own) await endpoints.updateTemplateAssignment(own.id, { enabled: false });
    else await endpoints.createTemplateAssignment({ resource_id: resource.id, enabled: false });
    invalidate();
    notify({ tone: "success", title: "Recommended alerts off", description: `${resource.name} no longer gets recommended alerts.` });
  };

  if (plan.isLoading) return <LoadingBlock label="Loading recommended alerts" />;
  if (plan.isError || !plan.data) {
    return <ErrorState error={plan.error} title="Unable to load recommended alerts." onRetry={() => void plan.refetch()} />;
  }
  const p = plan.data;
  if (!p.template) {
    return (
      <Card>
        <CardHeader title="Recommended alerts" />
        <CardContent>
          <p className="text-sm text-muted-foreground">
            There is no alert template for this resource type. Inventory items such as network interfaces have no metrics to alert on; use a custom rule
            if you need one.
          </p>
        </CardContent>
      </Card>
    );
  }
  const covered = !!p.assignment && p.assignment.enabled;
  const turnedOffHere = !!p.assignment && !p.assignment.enabled;
  return (
    <Card>
      <CardHeader
        title="Recommended alerts"
        description={
          covered && p.assignment ? (
            <>
              Covered by <span className="font-medium text-foreground">{scopeLabel(p.assignment)}</span> ({SCOPE_KIND[p.assignment.scope].toLowerCase()}),
              using the {p.template.display_name} template.
            </>
          ) : turnedOffHere ? (
            "Recommended alerts are turned off for this resource. This overrides any broader coverage."
          ) : (
            `Not covered. Turn on the ${p.template.display_name} template to alert on these metrics automatically.`
          )
        }
        actions={
          <span className="flex items-center gap-2">
            {covered ? (
              <Badge tone="healthy">
                <ShieldCheck className="size-3" aria-hidden="true" /> Covered
              </Badge>
            ) : (
              <Badge tone="neutral">{turnedOffHere ? "Off" : "Not covered"}</Badge>
            )}
          </span>
        }
      />
      <CardContent className="space-y-3 px-0">
        <PlanTable rules={p.rules} showCurrent={covered} />
        {canManage ? (
          <div className="flex flex-wrap gap-2 px-5">
            {covered ? (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    if (own) setCustomising(own);
                    else setApplyOpen(true);
                  }}
                >
                  <Pencil /> Customise for this resource
                </Button>
                <ConfirmButton
                  title={`Turn off recommended alerts for ${resource.name}?`}
                  description="This resource stops getting recommended alerts even though a broader coverage (its environment, project or everything) applies. You can turn them back on here."
                  confirmLabel="Turn off"
                  onConfirm={turnOff}
                >
                  <BellOff /> Turn off for this resource
                </ConfirmButton>
              </>
            ) : (
              <Button size="sm" disabled={enable.isPending} onClick={() => enable.mutate()}>
                <ShieldCheck /> {turnedOffHere ? "Turn recommended alerts back on" : "Enable recommended alerts"}
              </Button>
            )}
          </div>
        ) : null}
        {enable.isError ? (
          <div className="px-5">
            <ErrorState error={enable.error} compact />
          </div>
        ) : null}
      </CardContent>
      {applyOpen ? (
        <ApplyTemplatesDialog
          open={applyOpen}
          onOpenChange={setApplyOpen}
          initial={{ scope: "resource", resource }}
          onEditExisting={(id) => setCustomising(assignments.data?.find((a) => a.id === id) ?? null)}
        />
      ) : null}
      {customising ? (
        <CustomiseAssignmentDialog
          key={customising.id}
          assignment={customising}
          monitorKey={p.monitor_key}
          open={!!customising}
          onOpenChange={(o) => {
            if (!o) setCustomising(null);
          }}
        />
      ) : null}
    </Card>
  );
}

export function EnvironmentAlertCoverage({ projectId, environmentId, environmentName }: { projectId: string; environmentId: string; environmentName: string }) {
  const canManage = usePermission(PERMISSIONS.manageAlerts);
  const invalidate = useInvalidateCoverage();
  const { notify } = useToast();
  // The server works out which coverage decides (it may be broader than this user's own access).
  const coverage = useQuery({ queryKey: ["alert-coverage-effective", environmentId], queryFn: () => endpoints.effectiveCoverage(environmentId) });
  const apply = useMutation({
    mutationFn: () => endpoints.createTemplateAssignment({ project_id: projectId, environment_id: environmentId }),
    onSuccess: (created) => {
      invalidate();
      notify({ tone: "success", title: "Recommended alerts applied", description: `${environmentName}: ${created.covered_resources} resources covered.` });
    },
  });
  const on = !!coverage.data?.covered;
  const turnedOff = !!coverage.data && coverage.data.scope === "environment" && !coverage.data.covered;
  return (
    <Card>
      <CardContent className="space-y-2 pt-5">
        <p className="text-sm font-medium">Alert coverage</p>
        {coverage.isLoading ? (
          <p className="text-sm text-muted-foreground">Checking...</p>
        ) : on ? (
          <p className="text-sm text-muted-foreground">
            <ShieldCheck className="mr-1 inline size-4 text-healthy" aria-hidden="true" />
            Recommended alerts on, from <span className="font-medium text-foreground">{coverage.data?.label}</span>.
          </p>
        ) : turnedOff ? (
          <p className="text-sm text-muted-foreground">Recommended alerts are turned off for this environment.</p>
        ) : (
          <p className="text-sm text-muted-foreground">Not covered: resources here only alert through custom rules.</p>
        )}
        <div className="flex flex-wrap gap-2">
          {!on && !turnedOff && canManage ? (
            <Button size="sm" disabled={apply.isPending} onClick={() => apply.mutate()}>
              <ShieldCheck /> Apply recommended alerts to this environment
            </Button>
          ) : null}
          <Button asChild size="sm" variant="ghost">
            <Link to="/alerts?tab=templates">Alert templates</Link>
          </Button>
        </div>
        {apply.isError ? <ErrorState error={apply.error} compact /> : null}
      </CardContent>
    </Card>
  );
}
