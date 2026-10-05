import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { endpoints } from "@/api/endpoints";
import { Breadcrumbs, type Crumb } from "@/components/Breadcrumbs";
import { formatReading } from "@/components/resourceSignals";
import { HealthBadge, TimeAgo } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { ResourceDashboard } from "@/components/widgets/ResourceDashboard";
import { HealthReasons } from "@/components/widgets/ResourceWidgets";
import { AlertTableWidget } from "@/components/widgets/ResourceWidgets";
import { PERMISSIONS, usePermission } from "@/hooks/useMe";
import type { ResourceDetail } from "@/types/api";
import { cn } from "@/utils/cn";
import { formatDateTime, formatRelative, regionName, titleCase } from "@/utils/format";
import { paths } from "@/utils/paths";

/** Where this resource lives: Projects / CRM / Production / App Service / name. */
function resourceCrumbs(r: ResourceDetail): Crumb[] {
  if (r.project_id && r.project_name) {
    const crumbs: Crumb[] = [
      { label: "Projects", to: paths.projects() },
      { label: r.project_name, to: paths.project(r.project_id) },
    ];
    if (r.environment_id && r.environment_name) {
      crumbs.push({ label: r.environment_name, to: paths.environment(r.project_id, r.environment_id) });
      crumbs.push({ label: r.type_display_name, to: paths.environment(r.project_id, r.environment_id, "resources") });
    } else {
      crumbs.push({ label: r.type_display_name });
    }
    return [...crumbs, { label: r.name }];
  }
  return [{ label: "Resources", to: "/resources" }, { label: "Unassigned", to: "/resources?view=unassigned" }, { label: r.name }];
}

const READING_TONE: Record<string, string> = { critical: "text-critical", warning: "text-warning" };

/** The type-specific health metrics from the last evaluation: the numbers that decide this resource's status. */
function KeyMetrics({ resource }: { resource: ResourceDetail }) {
  const readings = resource.health_metrics ?? [];
  if (!readings.length) return null;
  return (
    <section aria-label="Key metrics" className="mb-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {readings.slice(0, 6).map((m) => (
          <div key={m.metric} className="rounded-lg border border-border bg-card px-4 py-3">
            <p className="truncate text-xs text-muted-foreground" title={m.label}>
              {m.label}
            </p>
            <p className={cn("tabular mt-1 text-xl font-semibold", READING_TONE[m.status] ?? "")}>{formatReading(m)}</p>
            {m.status !== "healthy" ? <p className={cn("text-xs capitalize", READING_TONE[m.status] ?? "text-muted-foreground")}>{m.status}</p> : null}
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        From the last health check {resource.health_evaluated_at ? <TimeAgo value={resource.health_evaluated_at} /> : "(not yet run)"}, averaged over each rule's window. Live
        charts are in the dashboard below.
      </p>
    </section>
  );
}

const SOURCE_LABELS: Record<string, string> = {
  tag: "Azure tags",
  name: "naming convention (resource or resource group name)",
  connection_default: "connection default",
  manual: "manual assignment",
  none: "nothing (unassigned)",
};

function AssignmentEditor({ resource }: { resource: ResourceDetail }) {
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects });
  const [projectId, setProjectId] = useState(resource.project_id ?? "");
  const [envId, setEnvId] = useState(resource.environment_id ?? "");
  const project = projects.data?.find((p) => p.id === projectId);
  const mutation = useMutation({
    mutationFn: () => endpoints.assign(resource.id, { project_id: projectId || null, environment_id: envId || null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["resource", resource.id] });
      void qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  return (
    <Card>
      <CardHeader
        title="Assignment"
        description={`Currently assigned by: ${SOURCE_LABELS[resource.assignment_source] ?? titleCase(resource.assignment_source)}. A manual assignment is kept across synchronisations; clearing it lets tags and the naming convention decide again.`}
      />
      <CardContent className="flex flex-wrap items-end gap-3">
        <Field label="Project" htmlFor="assign-project" className="min-w-48">
          <Select
            id="assign-project"
            value={projectId}
            onChange={(e) => {
              setProjectId(e.target.value);
              setEnvId("");
            }}
          >
            <option value="">Unassigned</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Environment" htmlFor="assign-env" className="min-w-48">
          <Select id="assign-env" value={envId} disabled={!project} onChange={(e) => setEnvId(e.target.value)}>
            <option value="">None</option>
            {project?.environments.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </Select>
        </Field>
        <Button disabled={mutation.isPending} onClick={() => mutation.mutate()}>
          Save assignment
        </Button>
        {mutation.isError ? <ErrorState error={mutation.error} compact /> : null}
      </CardContent>
    </Card>
  );
}

function ActivityTab({ resourceId }: { resourceId: string }) {
  const query = useQuery({ queryKey: ["activity", resourceId], queryFn: () => endpoints.activity(resourceId) });
  if (query.isLoading) return <LoadingBlock />;
  if (query.isError) return <ErrorState error={query.error} />;
  const entries = query.data ?? [];
  if (entries.length === 1 && entries[0].error) return <ErrorState error={new ApiError(502, { code: entries[0].error, message: entries[0].message ?? "Activity unavailable." })} />;
  return (
    <Card>
      <CardHeader title="Recent changes" description="Azure Resource Graph change history for this resource (last 7 days)" />
      <CardContent className="px-0">
        {entries.length === 0 ? (
          <EmptyState title="No changes recorded in the last 7 days." className="py-6" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>When</TH>
                <TH>Change</TH>
                <TH>Operation</TH>
                <TH>Changed by</TH>
              </TR>
            </THead>
            <tbody>
              {entries.map((e, i) => (
                <TR key={i}>
                  <TD className="whitespace-nowrap">{formatDateTime(e.changed_at)}</TD>
                  <TD>{e.change_type}</TD>
                  <TD className="font-mono text-xs">{e.operation ?? "-"}</TD>
                  <TD>{e.changed_by ?? "-"}</TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function KeyValueTable({ data, empty }: { data: Record<string, unknown>; empty: string }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <EmptyState title={empty} className="py-6" />;
  return (
    <Table>
      <THead>
        <TR>
          <TH>Name</TH>
          <TH>Value</TH>
        </TR>
      </THead>
      <tbody>
        {entries.map(([k, v]) => (
          <TR key={k}>
            <TD className="font-medium">{k}</TD>
            <TD className="font-mono text-xs break-all">{typeof v === "object" ? JSON.stringify(v) : String(v)}</TD>
          </TR>
        ))}
      </tbody>
    </Table>
  );
}

export function ResourceDetailPage() {
  const { resourceId = "" } = useParams();
  const qc = useQueryClient();
  const canManage = usePermission(PERMISSIONS.manageProjects);
  const resource = useQuery({ queryKey: ["resource", resourceId], queryFn: () => endpoints.resource(resourceId) });
  const dashboard = useQuery({
    queryKey: ["dashboard-for", resourceId],
    queryFn: () => endpoints.dashboardForResource(resourceId),
    retry: false,
  });
  const evaluate = useMutation({
    mutationFn: () => endpoints.evaluateHealth(resourceId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["resource", resourceId] }),
  });

  if (resource.isLoading) return <LoadingBlock label="Loading resource" />;
  if (resource.isError || !resource.data) {
    return <ErrorState error={resource.error} title="Unable to load this resource." onRetry={() => void resource.refetch()} />;
  }
  const r = resource.data;

  const extraTabs = [
    {
      key: "health",
      label: "Health",
      content: (
        <Card>
          <CardHeader
            title="Health"
            description={r.health_evaluated_at ? `Evaluated ${formatDateTime(r.health_evaluated_at)}` : "Not evaluated yet"}
            actions={<HealthBadge status={r.health_status} />}
          />
          <CardContent className="space-y-4">
            <HealthReasons reasons={r.health_reasons} status={r.health_status} />
            {r.azure_availability_state ? (
              <p className="text-xs text-muted-foreground">Azure Resource Health: {r.azure_availability_state}</p>
            ) : null}
          </CardContent>
        </Card>
      ),
    },
    {
      key: "alerts",
      label: "Alerts",
      content: (
        <AlertTableWidget
          resource={r}
          widget={{ id: "alerts", position: 0, section: "Alerts", widget_type: "alert_table", title: "Open alerts", width: 12, config: {} }}
        />
      ),
    },
    {
      key: "configuration",
      label: "Configuration",
      content: (
        <div className="space-y-4">
          <Card>
            <CardHeader title="Properties" description="Allow-listed properties captured during discovery" />
            <CardContent className="px-0">
              <KeyValueTable data={r.properties} empty="No properties were captured." />
            </CardContent>
          </Card>
          {canManage ? <AssignmentEditor resource={r} /> : null}
        </div>
      ),
    },
    {
      key: "tags",
      label: "Tags",
      content: (
        <Card>
          <CardContent className="px-0 pt-2">
            <KeyValueTable data={r.tags} empty="This resource has no tags." />
          </CardContent>
        </Card>
      ),
    },
    { key: "activity", label: "Activity", content: <ActivityTab resourceId={r.id} /> },
  ];

  const meta = [
    { label: "Region", value: regionName(r.location) },
    { label: "Resource group", value: r.resource_group },
    {
      label: "Project",
      value: r.project_name ? `${r.project_name} / ${r.environment_name ?? "No environment"}` : "Unassigned",
    },
    ...(r.sku ? [{ label: "SKU", value: r.sku }] : []),
    { label: "Last seen", value: formatRelative(r.last_seen_at) },
  ];

  return (
    <>
      <Breadcrumbs items={resourceCrumbs(r)} />
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="truncate text-xl font-semibold tracking-tight">{r.name}</h1>
            <HealthBadge status={r.health_status} />
            <span className="text-sm text-muted-foreground">{r.type_display_name}</span>
          </div>
          <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {meta.map((m) => (
              <div key={m.label} className="flex min-w-0 gap-1.5">
                <dt className="text-muted-foreground">{m.label}:</dt>
                <dd className="truncate" title={m.value}>
                  {m.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="secondary" size="sm" disabled={evaluate.isPending} onClick={() => evaluate.mutate()}>
            <RefreshCw className={evaluate.isPending ? "animate-spin" : undefined} /> Re-evaluate
          </Button>
          <Button variant="secondary" size="sm" asChild>
            <a href={r.portal_url} target="_blank" rel="noopener noreferrer">
              <ExternalLink /> Open in Azure
            </a>
          </Button>
        </div>
      </div>
      {evaluate.isError ? <ErrorState error={evaluate.error} compact className="mb-4" /> : null}
      <KeyMetrics resource={r} />
      {dashboard.isError && !(dashboard.error instanceof ApiError && dashboard.error.status === 404) ? (
        <ErrorState error={dashboard.error} className="mb-4" />
      ) : null}
      {dashboard.isLoading ? (
        <LoadingBlock />
      ) : (
        <ResourceDashboard dashboard={dashboard.data ?? null} resource={r} extraTabs={extraTabs} />
      )}
    </>
  );
}
