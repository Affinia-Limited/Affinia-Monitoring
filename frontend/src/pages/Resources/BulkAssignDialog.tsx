import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { endpoints } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

const CONCURRENCY = 4;

/** Runs `task` over `items` with a small concurrency limit, reporting progress. */
export async function runPool<T>(items: T[], task: (item: T) => Promise<void>, onProgress: (done: number) => void): Promise<number> {
  let next = 0;
  let done = 0;
  let failed = 0;
  const worker = async () => {
    while (next < items.length) {
      const item = items[next++];
      try {
        await task(item);
      } catch {
        failed += 1;
      }
      done += 1;
      onProgress(done);
    }
  };
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, items.length) }, worker));
  return failed;
}

export function BulkAssignDialog({
  ids,
  open,
  onOpenChange,
  onDone,
}: {
  ids: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, enabled: open });
  const [projectId, setProjectId] = useState("");
  const [envId, setEnvId] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const project = projects.data?.find((p) => p.id === projectId);
  const running = progress !== null;

  const run = async () => {
    setProgress(0);
    const failed = await runPool(
      ids,
      async (id) => {
        await endpoints.assign(id, { project_id: projectId || null, environment_id: envId || null });
      },
      setProgress,
    );
    const target = project ? `${project.name}${envId ? ` / ${project.environments.find((e) => e.id === envId)?.name}` : ""}` : "Unassigned";
    const ok = ids.length - failed;
    notify({
      tone: failed ? "warning" : "success",
      title: `${ok} resource${ok === 1 ? "" : "s"} ${project ? `assigned to ${target}` : "unassigned"}`,
      description: failed ? `${failed} could not be updated. Check your permissions and try again.` : "Manual assignments are kept across synchronisations.",
    });
    await Promise.all(
      [["resources"], ["facets"], ["overview"], ["projects"], ["resource-counts"]].map((queryKey) => qc.invalidateQueries({ queryKey })),
    );
    setProgress(null);
    onOpenChange(false);
    onDone();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !running && onOpenChange(o)}>
      <DialogContent
        title={`Assign ${ids.length} resource${ids.length === 1 ? "" : "s"}`}
        description="Pick a project and, optionally, an environment. Choosing no project clears the assignment so tags decide again."
        footer={
          <>
            <Button variant="ghost" disabled={running} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button disabled={running || ids.length === 0} onClick={() => void run()}>
              {running ? `Assigning ${progress} of ${ids.length}...` : "Assign"}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Project" htmlFor="bulk-project">
            <Select
              id="bulk-project"
              value={projectId}
              disabled={running}
              onChange={(e) => {
                setProjectId(e.target.value);
                setEnvId("");
              }}
            >
              <option value="">No project (unassign)</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Environment" htmlFor="bulk-env">
            <Select id="bulk-env" value={envId} disabled={!project || running} onChange={(e) => setEnvId(e.target.value)}>
              <option value="">None</option>
              {project?.environments.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {running ? (
          <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={ids.length} aria-valuenow={progress ?? 0}>
            <div className="h-full bg-primary transition-[width]" style={{ width: `${((progress ?? 0) / Math.max(ids.length, 1)) * 100}%` }} />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
