import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { KeyValue, PageHeader } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Select, Switch } from "@/components/ui/form";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PERMISSIONS, useMe, usePermission } from "@/hooks/useMe";
import { type ThemePreference, useTheme } from "@/stores/theme";
import type { HealthRule } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatDateTime, titleCase } from "@/utils/format";

function UsersTab() {
  const { data: me } = useMe();
  const canManage = usePermission(PERMISSIONS.manageUsers);
  const roles = useQuery({ queryKey: ["roles"], queryFn: endpoints.roles });
  return (
    <div className="space-y-4">
      {canManage ? (
        <Card>
          <CardHeader
            title="Users"
            description="Access is admin-controlled: signing in with Microsoft Entra ID only works for users added here."
            actions={
              <Button asChild size="sm">
                <Link to="/settings/users">Manage users</Link>
              </Button>
            }
          />
        </Card>
      ) : null}
      <Card>
        <CardHeader title="Roles" description="Permissions are enforced by the API; the interface only hides controls you cannot use." />
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {roles.data?.map((r) => (
            <div key={r.key} className={cn("rounded-md border border-border p-3", me?.role === r.key && "border-primary")}>
              <p className="text-sm font-semibold">
                {r.name} {me?.role === r.key ? <Badge tone="info">Your role</Badge> : null}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">{r.description}</p>
              <p className="mt-2 text-[11px] text-muted-foreground">{r.permissions.join(", ")}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function ThresholdRow({ rule, editable }: { rule: HealthRule; editable: boolean }) {
  const qc = useQueryClient();
  const [warning, setWarning] = useState(rule.warning_threshold === null ? "" : String(rule.warning_threshold));
  const [critical, setCritical] = useState(rule.critical_threshold === null ? "" : String(rule.critical_threshold));
  const [enabled, setEnabled] = useState(rule.enabled);
  const save = useMutation({
    mutationFn: () =>
      endpoints.setHealthRule({
        monitor_key: rule.monitor_key,
        metric_name: rule.metric_name,
        warning_threshold: warning === "" ? null : Number(warning),
        critical_threshold: critical === "" ? null : Number(critical),
        enabled,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["health-rules"] }),
  });
  const dirty =
    warning !== (rule.warning_threshold === null ? "" : String(rule.warning_threshold)) ||
    critical !== (rule.critical_threshold === null ? "" : String(rule.critical_threshold)) ||
    enabled !== rule.enabled;
  const op = rule.operator === "lt" || rule.operator === "lte" ? "below" : "above";
  return (
    <TR>
      <TD>
        <div className="font-medium">{rule.metric_label}</div>
        <div className="text-xs text-muted-foreground">
          {op} threshold, {rule.window_minutes} min window{rule.overridden ? ", customised" : ""}
        </div>
      </TD>
      <TD>
        <Input aria-label={`${rule.monitor_name} ${rule.metric_label} warning`} className="h-8 w-24" type="number" step="any" value={warning} disabled={!editable} onChange={(e) => setWarning(e.target.value)} />
      </TD>
      <TD>
        <Input aria-label={`${rule.monitor_name} ${rule.metric_label} critical`} className="h-8 w-24" type="number" step="any" value={critical} disabled={!editable} onChange={(e) => setCritical(e.target.value)} />
      </TD>
      <TD className="text-xs text-muted-foreground">
        {rule.default_warning ?? "-"} / {rule.default_critical ?? "-"} {rule.unit}
      </TD>
      <TD>
        <Switch aria-label={`${rule.metric_label} enabled`} checked={enabled} disabled={!editable} onCheckedChange={setEnabled} />
      </TD>
      <TD className="text-right">
        {editable ? (
          <Button size="sm" variant="outline" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        ) : null}
        {save.isError ? <ErrorState error={save.error} compact className="mt-1" /> : null}
      </TD>
    </TR>
  );
}

function ThresholdsTab() {
  const editable = usePermission(PERMISSIONS.manageSettings);
  const rules = useQuery({ queryKey: ["health-rules"], queryFn: endpoints.healthRules });
  if (rules.isLoading) return <LoadingBlock />;
  if (rules.isError) return <ErrorState error={rules.error} />;
  const byMonitor = new Map<string, HealthRule[]>();
  for (const r of rules.data ?? []) byMonitor.set(r.monitor_name, [...(byMonitor.get(r.monitor_name) ?? []), r]);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Health status is calculated from these thresholds together with Azure Resource Health. Changes apply at the next evaluation.
      </p>
      {[...byMonitor.entries()].map(([name, items]) => (
        <Card key={name}>
          <CardHeader title={name} />
          <CardContent className="px-0">
            <Table>
              <THead>
                <TR>
                  <TH>Metric</TH>
                  <TH>Warning</TH>
                  <TH>Critical</TH>
                  <TH>Default</TH>
                  <TH>Enabled</TH>
                  <TH />
                </TR>
              </THead>
              <tbody>
                {items.map((r) => (
                  <ThresholdRow key={`${r.monitor_key}-${r.metric_name}-${r.warning_threshold}-${r.critical_threshold}-${r.enabled}`} rule={r} editable={editable} />
                ))}
              </tbody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function AuditTab() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [result, setResult] = useState("");
  const query = useQuery({
    queryKey: ["audit", page, action, result],
    queryFn: () => endpoints.auditLogs({ page, page_size: 50, action, result }),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.total ?? 0) / 50));
  return (
    <Card>
      <div className="flex flex-wrap gap-3 border-b border-border p-3">
        <Input aria-label="Filter by action prefix" className="h-8 w-56" placeholder="Action prefix, e.g. azure." value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} />
        <Select aria-label="Filter by result" className="h-8 w-40 text-xs" value={result} onChange={(e) => { setResult(e.target.value); setPage(1); }}>
          <option value="">All results</option>
          <option value="success">Success</option>
          <option value="failure">Failure</option>
          <option value="denied">Denied</option>
        </Select>
      </div>
      {query.isLoading ? (
        <div className="p-4">
          <LoadingBlock />
        </div>
      ) : query.isError ? (
        <div className="p-4">
          <ErrorState error={query.error} />
        </div>
      ) : (
        <>
          <Table>
            <THead>
              <TR>
                <TH>Time</TH>
                <TH>Actor</TH>
                <TH>Action</TH>
                <TH>Target</TH>
                <TH>Result</TH>
                <TH>IP address</TH>
              </TR>
            </THead>
            <tbody>
              {query.data?.items.map((e) => (
                <TR key={e.id}>
                  <TD className="whitespace-nowrap">{formatDateTime(e.created_at)}</TD>
                  <TD>{e.actor}</TD>
                  <TD className="font-mono text-xs">{e.action}</TD>
                  <TD className="max-w-64 truncate text-xs" title={e.target_id ?? ""}>
                    {e.target_type ? `${e.target_type}: ` : ""}
                    {e.target_id ?? "-"}
                  </TD>
                  <TD>
                    <Badge tone={e.result === "success" ? "healthy" : e.result === "denied" ? "warning" : "critical"}>{titleCase(e.result)}</Badge>
                  </TD>
                  <TD className="font-mono text-xs">{e.ip_address ?? "-"}</TD>
                </TR>
              ))}
            </tbody>
          </Table>
          <div className="flex items-center justify-end gap-1 border-t border-border px-4 py-2 text-xs text-muted-foreground">
            <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              <ChevronLeft />
            </Button>
            Page {page} of {pages}
            <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)}>
              <ChevronRight />
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}

function AppearanceTab() {
  const { preference, setPreference } = useTheme();
  const options: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
  ];
  return (
    <Card>
      <CardHeader title="Theme" description="Charts and status colours adapt to the selected theme." />
      <CardContent className="flex flex-wrap gap-3">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={preference === o.value}
            onClick={() => setPreference(o.value)}
            className={cn(
              "flex w-36 flex-col items-center gap-2 rounded-md border border-border p-4 text-sm hover:bg-muted",
              preference === o.value && "border-primary bg-accent text-accent-foreground",
            )}
          >
            <o.icon className="size-5" />
            {o.label}
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

function AboutTab() {
  const { data: me } = useMe();
  return (
    <Card>
      <CardHeader title="About this deployment" />
      <CardContent>
        <KeyValue
          items={[
            { label: "Organisation", value: me?.organization_name },
            { label: "Authentication", value: me?.auth_mode === "entra" ? "Microsoft Entra ID" : "Development (no sign-in)" },
            { label: "Azure provider", value: me?.azure_provider === "mock" ? "Mock (demo data)" : "Azure" },
            { label: "Your role", value: me ? titleCase(me.role) : "-" },
            { label: "Interface version", value: "0.1.0" },
          ]}
        />
      </CardContent>
    </Card>
  );
}

const SETTINGS_TABS = ["users", "thresholds", "audit", "appearance", "about"];

export function SettingsPage() {
  const canAudit = usePermission(PERMISSIONS.viewAudit);
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") ?? "users";
  const tab = SETTINGS_TABS.includes(requested) && (requested !== "audit" || canAudit) ? requested : "users";
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs
        value={tab}
        onValueChange={(v) =>
          setParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              if (v === "users") next.delete("tab");
              else next.set("tab", v);
              return next;
            },
            { replace: true },
          )
        }
      >
        <TabsList aria-label="Settings sections">
          <TabsTrigger value="users">Users and roles</TabsTrigger>
          <TabsTrigger value="thresholds">Health thresholds</TabsTrigger>
          {canAudit ? <TabsTrigger value="audit">Audit log</TabsTrigger> : null}
          <TabsTrigger value="appearance">Appearance</TabsTrigger>
          <TabsTrigger value="about">About</TabsTrigger>
        </TabsList>
        <TabsContent value="users">
          <UsersTab />
        </TabsContent>
        <TabsContent value="thresholds">
          <ThresholdsTab />
        </TabsContent>
        {canAudit ? (
          <TabsContent value="audit">
            <AuditTab />
          </TabsContent>
        ) : null}
        <TabsContent value="appearance">
          <AppearanceTab />
        </TabsContent>
        <TabsContent value="about">
          <AboutTab />
        </TabsContent>
      </Tabs>
    </>
  );
}
