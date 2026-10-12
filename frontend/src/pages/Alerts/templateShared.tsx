import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/form";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import type { AlertTemplate, AlertTemplateAssignment, AlertTier, Operator, TemplateRule, TemplateRuleOverride } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatValue } from "@/utils/format";

export type Tier = "info" | "warning" | "critical";
export const TIERS: Tier[] = ["info", "warning", "critical"];
export const TIER_LABEL: Record<Tier, string> = { info: "Info", warning: "Warning", critical: "Critical" };
const TIER_TEXT: Record<Tier, string> = { info: "text-info", warning: "text-warning", critical: "text-critical" };

export const OPERATOR_WORD: Record<Operator, string> = { gt: "above", gte: "at or above", lt: "below", lte: "at or below" };

/** "<monitor_key>:<metric>", the key of an assignment override. */
export function overrideKey(monitorKey: string, metric: string): string {
  return `${monitorKey}:${metric}`;
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = minutes / 60;
  return Number.isInteger(hours) ? `${hours} h` : `${minutes} min`;
}

/** Where an assignment applies, in words: "app-crm-prod-uks", "CRM / Production", "PRISM (all environments)", "All projects". */
export function scopeLabel(a: Pick<AlertTemplateAssignment, "scope" | "resource_name" | "project_name" | "environment_name">): string {
  switch (a.scope) {
    case "resource":
      return a.resource_name ?? "One resource";
    case "environment":
      return `${a.project_name ?? "Project"} / ${a.environment_name ?? "Environment"}`;
    case "project":
      return `${a.project_name ?? "Project"} (all environments)`;
    default:
      return "All projects";
  }
}

export const SCOPE_KIND: Record<AlertTemplateAssignment["scope"], string> = {
  resource: "Resource",
  environment: "Environment",
  project: "Project",
  organization: "Everything",
};

/**
 * Thresholds must escalate in the direction of the condition: for "above", Info < Warning < Critical;
 * for "below", Info > Warning > Critical. Empty tiers are skipped. The API applies the same rule.
 */
export function tierOrderError(operator: Operator, values: Record<Tier, number | null>): string | null {
  const set = TIERS.filter((t) => values[t] !== null).map((t) => ({ tier: t, value: values[t] as number }));
  if (set.length === 0) return "Set at least one threshold, or turn the alert off.";
  const rising = operator === "gt" || operator === "gte";
  for (let i = 1; i < set.length; i += 1) {
    const ok = rising ? set[i].value > set[i - 1].value : set[i].value < set[i - 1].value;
    if (!ok) {
      return rising
        ? `For an "above" condition each level must be higher than the one before it (Info < Warning < Critical): ${TIER_LABEL[set[i].tier]} must be higher than ${TIER_LABEL[set[i - 1].tier]}.`
        : `For a "below" condition each level must be lower than the one before it (Info > Warning > Critical): ${TIER_LABEL[set[i].tier]} must be lower than ${TIER_LABEL[set[i - 1].tier]}.`;
    }
  }
  return null;
}

/** "" -> null; anything else -> number (NaN when not a number). */
export function parseThreshold(text: string): number | null {
  const trimmed = text.trim();
  return trimmed === "" ? null : Number(trimmed);
}

export function thresholdText(value: number | null): string {
  return value === null ? "" : String(value);
}

/** A threshold with its unit and level name, never colour alone. */
export function TierValue({ tier, value, unit }: { tier: Tier; value: number | null; unit: string }) {
  if (value === null) return <span className="text-muted-foreground">-</span>;
  return (
    <span className={cn("tabular font-medium", TIER_TEXT[tier])} title={`${TIER_LABEL[tier]} threshold`}>
      {formatValue(value, unit)}
    </span>
  );
}

const CURRENT_TONE: Record<AlertTier, "critical" | "warning" | "info" | "healthy" | "neutral"> = {
  critical: "critical",
  warning: "warning",
  info: "info",
  ok: "healthy",
  unknown: "neutral",
};
const CURRENT_LABEL: Record<AlertTier, string> = { critical: "Critical", warning: "Warning", info: "Info", ok: "OK", unknown: "No data" };

export function CurrentTierBadge({ tier }: { tier: AlertTier }) {
  return <Badge tone={CURRENT_TONE[tier]}>{CURRENT_LABEL[tier]}</Badge>;
}

/** The effective values of a rule after an override. */
export function applyOverride(rule: TemplateRule, override: TemplateRuleOverride | undefined): TemplateRule {
  if (!override) return rule;
  return {
    ...rule,
    enabled: override.enabled ?? rule.enabled,
    info: override.info !== undefined ? override.info : rule.info,
    warning: override.warning !== undefined ? override.warning : rule.warning,
    critical: override.critical !== undefined ? override.critical : rule.critical,
  };
}

/** Only what differs from the template: an override that changes nothing is dropped. */
export function diffOverride(rule: TemplateRule, next: Pick<TemplateRule, "enabled" | "info" | "warning" | "critical">): TemplateRuleOverride | null {
  const out: TemplateRuleOverride = {};
  if (next.enabled !== rule.enabled) out.enabled = next.enabled;
  for (const t of TIERS) if (next[t] !== rule[t]) out[t] = next[t];
  return Object.keys(out).length ? out : null;
}

/** Rules of one template; editable cells write overrides into the given map. */
export function RuleOverridesTable({
  template,
  overrides,
  onChange,
  editable,
}: {
  template: AlertTemplate;
  overrides: Record<string, TemplateRuleOverride>;
  onChange: (next: Record<string, TemplateRuleOverride>) => void;
  editable: boolean;
}) {
  const setRule = (rule: TemplateRule, next: Pick<TemplateRule, "enabled" | "info" | "warning" | "critical">) => {
    const key = overrideKey(template.monitor_key, rule.metric);
    const diff = diffOverride(rule, next);
    const copy = { ...overrides };
    if (diff) copy[key] = diff;
    else delete copy[key];
    onChange(copy);
  };
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
            <TH>Window</TH>
            <TH>Every</TH>
            <TH>On</TH>
          </TR>
        </THead>
        <tbody>
          {template.rules.map((base) => {
            const key = overrideKey(template.monitor_key, base.metric);
            const rule = applyOverride(base, overrides[key]);
            const values = { info: rule.info, warning: rule.warning, critical: rule.critical };
            const error = rule.enabled ? tierOrderError(base.operator, values) : null;
            return (
              <TR key={base.metric} className={cn(!rule.enabled && "opacity-60")}>
                <TD>
                  <div className="font-medium">{base.label}</div>
                  {overrides[key] ? <div className="text-xs text-primary">Changed for this coverage</div> : null}
                  {error ? (
                    <div role="alert" className="text-xs text-critical">
                      {error}
                    </div>
                  ) : null}
                </TD>
                <TD className="whitespace-nowrap text-muted-foreground">{OPERATOR_WORD[base.operator]}</TD>
                {TIERS.map((t) => (
                  <TD key={t}>
                    {editable ? (
                      <Input
                        aria-label={`${base.label} ${TIER_LABEL[t]} threshold${base.unit ? ` (${base.unit})` : ""}`}
                        className="h-8 w-24"
                        type="number"
                        step="any"
                        value={thresholdText(rule[t])}
                        disabled={!rule.enabled}
                        onChange={(e) => setRule(base, { ...values, enabled: rule.enabled, [t]: parseThreshold(e.target.value) })}
                      />
                    ) : (
                      <TierValue tier={t} value={rule[t]} unit={base.unit} />
                    )}
                  </TD>
                ))}
                <TD className="whitespace-nowrap text-muted-foreground">{formatMinutes(base.window_minutes)}</TD>
                <TD className="whitespace-nowrap text-muted-foreground">{formatMinutes(base.frequency_minutes)}</TD>
                <TD>
                  <input
                    type="checkbox"
                    aria-label={`${base.label} alert on`}
                    checked={rule.enabled}
                    disabled={!editable}
                    onChange={(e) => setRule(base, { ...values, enabled: e.target.checked })}
                  />
                </TD>
              </TR>
            );
          })}
        </tbody>
      </Table>
    </div>
  );
}

/** Any override in the map that breaks tier order (blocks saving). */
export function overridesError(templates: AlertTemplate[], overrides: Record<string, TemplateRuleOverride>): string | null {
  for (const template of templates) {
    for (const base of template.rules) {
      const rule = applyOverride(base, overrides[overrideKey(template.monitor_key, base.metric)]);
      if (!rule.enabled) continue;
      const values = { info: rule.info, warning: rule.warning, critical: rule.critical };
      if (TIERS.some((t) => values[t] !== null && Number.isNaN(values[t]))) return `${base.label}: enter numbers only.`;
      const error = tierOrderError(base.operator, values);
      if (error) return `${base.label}: ${error}`;
    }
  }
  return null;
}
