import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { endpoints } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

/** Runs health, template and custom-rule evaluation now instead of waiting for the next scheduled check. */
export function EvaluateNowButton() {
  const qc = useQueryClient();
  const { notify } = useToast();
  const evaluate = useMutation({
    mutationFn: endpoints.evaluateAlertRules,
    onSuccess: (result) => {
      notify({ tone: "success", title: "Evaluation started", description: result.message });
      // Alerts from this run land within a minute; refresh the views shortly after.
      window.setTimeout(() => {
        void qc.invalidateQueries({ queryKey: ["alerts"] });
        void qc.invalidateQueries({ queryKey: ["alert-plan"] });
      }, 20_000);
    },
    onError: (error) =>
      notify({ tone: "warning", title: "Evaluation not started", description: error instanceof Error ? error.message : "Try again shortly." }),
  });
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={evaluate.isPending}
      onClick={() => evaluate.mutate()}
      title="Check every alert against the latest metrics now, instead of waiting for the next scheduled check"
    >
      <Play /> Evaluate now
    </Button>
  );
}
