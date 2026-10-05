import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { endpoints } from "@/api/endpoints";
import { KeyValue } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingBlock } from "@/components/ui/states";
import type { AvailableSubscription, SyncRun } from "@/types/api";
import { formatDateTime } from "@/utils/format";
import { SyncProgress } from "./SyncProgress";

export const MOCK_TENANT = "00000000-0000-4000-8000-00000000d3a0";
export const MOCK_SUBSCRIPTIONS = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"];
const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const POLL_MS = 1500;

function parseIds(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((s) => s.trim().toLowerCase()).filter(Boolean))];
}

export function AddConnectionWizard({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const qc = useQueryClient();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const identity = useQuery({ queryKey: ["azure-identity"], queryFn: endpoints.identity, enabled: open });
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, enabled: open });
  const [name, setName] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [subs, setSubs] = useState("");
  const [projectId, setProjectId] = useState("");
  const [envId, setEnvId] = useState("");
  const [available, setAvailable] = useState<AvailableSubscription[] | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const isMock = identity.data?.is_mock ?? false;

  useEffect(() => {
    if (isMock && !tenantId && !subs) {
      setTenantId(MOCK_TENANT);
      setSubs(MOCK_SUBSCRIPTIONS.join("\n"));
      setName((n) => n || "Demo subscriptions");
    }
  }, [isMock, tenantId, subs]);

  const load = useMutation({
    mutationFn: () => endpoints.availableSubscriptions(tenantId.trim()),
    onSuccess: setAvailable,
  });
  const create = useMutation({
    mutationFn: () =>
      endpoints.createConnection({
        name: name.trim(),
        tenant_id: tenantId.trim().toLowerCase(),
        subscription_ids: parseIds(subs),
        default_project_id: projectId || null,
        default_environment_id: envId || null,
      }),
    onSuccess: (result) => {
      setRunId(result.sync_run.id);
      setStep(3);
      void qc.invalidateQueries({ queryKey: ["connections"] });
    },
  });
  const run = useQuery({
    queryKey: ["sync-run", runId],
    queryFn: () => endpoints.syncRun(runId as string),
    enabled: !!runId,
    refetchInterval: (q) => {
      const status = (q.state.data as SyncRun | undefined)?.status;
      return status === "succeeded" || status === "failed" ? false : POLL_MS;
    },
  });
  const finished = run.data?.status === "succeeded" || run.data?.status === "failed";

  useEffect(() => {
    if (finished) {
      void qc.invalidateQueries({ queryKey: ["connections"] });
      void qc.invalidateQueries({ queryKey: ["overview"] });
      void qc.invalidateQueries({ queryKey: ["projects"] });
    }
  }, [finished, qc]);

  const ids = parseIds(subs);
  const invalidIds = ids.filter((id) => !GUID.test(id));
  const tenantValid = GUID.test(tenantId.trim());
  const canSubmit = name.trim() && tenantValid && ids.length > 0 && invalidIds.length === 0;
  const project = projects.data?.find((p) => p.id === projectId);

  const close = (o: boolean) => {
    onOpenChange(o);
    if (!o) {
      setStep(1);
      setRunId(null);
      create.reset();
    }
  };

  const connection = create.data?.connection;
  const footer =
    step === 1 ? (
      <Button onClick={() => setStep(2)}>Continue</Button>
    ) : step === 2 ? (
      <>
        <Button variant="ghost" onClick={() => setStep(1)}>
          Back
        </Button>
        <Button disabled={!canSubmit || create.isPending} onClick={() => create.mutate()}>
          Connect
        </Button>
      </>
    ) : (
      <Button disabled={!finished} onClick={() => close(false)}>
        {finished ? "Done" : "Working..."}
      </Button>
    );

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent title="Add Azure subscription" description={`Step ${step} of 3`} className="max-w-2xl" footer={footer}>
        {step === 1 ? (
          identity.isLoading ? (
            <LoadingBlock />
          ) : identity.isError ? (
            <ErrorState error={identity.error} />
          ) : (
            <div className="space-y-4 text-sm">
              <div className="flex gap-3 rounded-md border border-healthy/30 bg-healthy/5 p-3">
                <ShieldCheck className="mt-0.5 size-5 shrink-0 text-healthy" />
                <p>
                  No passwords or client secrets are requested or stored. The platform signs in to Azure with its own
                  {identity.data?.auth_methods.includes("workload_identity") ? " managed identity or workload identity" : " managed identity"}.
                  You grant that identity read-only roles on the subscriptions you want to monitor.
                </p>
              </div>
              <KeyValue
                items={[
                  { label: "Platform identity client ID", value: identity.data?.client_id ?? "Not configured" },
                  { label: "Home tenant", value: identity.data?.home_tenant_id ?? "Not configured" },
                  { label: "Provider", value: isMock ? "Mock (demo data)" : "Azure" },
                ]}
              />
              <div>
                <p className="mb-2 font-medium">Grant these roles to the platform identity</p>
                <ul className="divide-y divide-border rounded-md border border-border">
                  {identity.data?.required_roles.map((r) => (
                    <li key={r.role} className="p-3">
                      <p className="font-medium">{r.role}</p>
                      <p className="text-xs text-muted-foreground">
                        Scope: {r.scope}. {r.purpose}.
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )
        ) : null}

        {step === 2 ? (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (canSubmit) create.mutate();
            }}
          >
            <Field label="Connection name" htmlFor="conn-name">
              <Input id="conn-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="CRM Production" />
            </Field>
            <Field label="Tenant ID" htmlFor="conn-tenant" error={tenantId && !tenantValid ? "Enter the tenant ID as a GUID." : null}>
              <Input id="conn-tenant" value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="00000000-0000-0000-0000-000000000000" />
            </Field>
            <div className="space-y-2">
              <Field
                label="Subscription IDs"
                htmlFor="conn-subs"
                hint="One per line or comma-separated."
                error={invalidIds.length ? `Not a valid subscription ID: ${invalidIds[0]}` : null}
              >
                <Textarea id="conn-subs" rows={3} className="font-mono text-xs" value={subs} onChange={(e) => setSubs(e.target.value)} />
              </Field>
              <Button variant="outline" size="sm" disabled={!tenantValid || load.isPending} onClick={() => load.mutate()}>
                Load subscriptions the platform can already read
              </Button>
              {load.isError ? <ErrorState error={load.error} compact /> : null}
              {available ? (
                available.length === 0 ? (
                  <p className="text-xs text-muted-foreground">The platform identity cannot read any subscription in this tenant yet.</p>
                ) : (
                  <div className="space-y-1 rounded-md border border-border p-2">
                    {available.map((s) => (
                      <label key={s.subscription_id} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={ids.includes(s.subscription_id.toLowerCase())}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? [...ids, s.subscription_id.toLowerCase()]
                              : ids.filter((x) => x !== s.subscription_id.toLowerCase());
                            setSubs(next.join("\n"));
                          }}
                        />
                        {s.display_name} <span className="font-mono text-xs text-muted-foreground">{s.subscription_id}</span>
                      </label>
                    ))}
                  </div>
                )
              ) : null}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Default project (optional)" htmlFor="conn-project" hint="Used when a resource has no matching project tag.">
                <Select
                  id="conn-project"
                  value={projectId}
                  onChange={(e) => {
                    setProjectId(e.target.value);
                    setEnvId("");
                  }}
                >
                  <option value="">None</option>
                  {projects.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Default environment (optional)" htmlFor="conn-env">
                <Select id="conn-env" value={envId} disabled={!project} onChange={(e) => setEnvId(e.target.value)}>
                  <option value="">None</option>
                  {project?.environments.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            {create.isError ? <ErrorState error={create.error} /> : null}
            <button type="submit" hidden />
          </form>
        ) : null}

        {step === 3 ? (
          <div className="space-y-4">
            <p className="text-sm font-medium">{finished ? (run.data?.status === "succeeded" ? "Setup complete." : "Setup failed.") : "Connecting Azure..."}</p>
            {run.data ? <SyncProgress run={run.data} /> : <LoadingBlock />}
            {run.isError ? <ErrorState error={run.error} /> : null}
            {run.data?.status === "failed" ? (
              <div role="alert" className="rounded-md border border-critical/30 bg-critical/5 p-3 text-sm">
                {run.data.error_message ?? "The synchronisation failed."}
                {run.data.error_code === "AZURE_PERMISSION_DENIED" ? (
                  <p className="mt-1 text-xs text-muted-foreground">Check that the platform identity has the Reader and Monitoring Reader roles.</p>
                ) : null}
              </div>
            ) : null}
            {run.data?.status === "succeeded" && connection ? (
              <div className="rounded-md border border-healthy/30 bg-healthy/5 p-4">
                <p className="mb-3 flex items-center gap-2 text-sm font-medium">
                  <CheckCircle2 className="size-4 text-healthy" /> Connected successfully
                </p>
                <KeyValue
                  items={[
                    { label: "Subscription", value: connection.name },
                    { label: "Tenant", value: connection.tenant_id },
                    { label: "Resources discovered", value: String(run.data.stats.discovered ?? 0) },
                    { label: "Last synchronisation", value: formatDateTime(run.data.finished_at) },
                  ]}
                />
              </div>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
