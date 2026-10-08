import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { AlertTable } from "@/components/AlertTable";
import { LiveMark } from "@/components/live";
import { HealthBadge } from "@/components/status";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useLiveResources } from "@/hooks/useLiveResources";
import type { HealthReason } from "@/types/api";
import { formatBytes, formatDateTime, formatValue, regionName } from "@/utils/format";
import { configString, type WidgetProps } from "./types";
import { Unavailable, WidgetError, WidgetFrame, WidgetLoading } from "./WidgetFrame";

const OPERATOR_TEXT: Record<string, string> = { gt: "above", gte: "at or above", lt: "below", lte: "at or below" };

export function describeReason(reason: HealthReason): string {
  if (reason.signal === "metric" && reason.value !== undefined) {
    const unit = reason.unit ?? "";
    return `${reason.label ?? reason.metric}: ${formatValue(reason.value, unit)} is ${OPERATOR_TEXT[reason.operator ?? ""] ?? "past"} the ${reason.severity} threshold of ${formatValue(reason.threshold ?? null, unit)} (last ${reason.window_minutes ?? 15} minutes)`;
  }
  if (reason.signal === "resource_health") return `Azure Resource Health: ${reason.message}`;
  return reason.message;
}

export function HealthReasons({ reasons, status }: { reasons: HealthReason[]; status?: string }) {
  if (reasons.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {status === "unknown" ? "No health signals could be read for this resource yet." : "All health signals are within their thresholds."}
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {reasons.map((r, i) => (
        <li key={i} className="flex items-start gap-2 text-sm">
          <HealthBadge status={r.severity} className="mt-0.5" />
          <span>{describeReason(r)}</span>
        </li>
      ))}
    </ul>
  );
}

export function ResourceHealthCard({ widget, resource }: WidgetProps) {
  // Same query as the page header, so no extra request.
  const live = useLiveResources([resource.id]).byId[resource.id];
  return (
    <WidgetFrame title={widget.title}>
      <div className="flex items-center gap-2">
        <HealthBadge status={live?.status ?? resource.health_status} />
        {live ? (
          <LiveMark />
        ) : (
          <span className="text-xs text-muted-foreground">
            {resource.health_evaluated_at ? `Evaluated ${formatDateTime(resource.health_evaluated_at)}` : "Not evaluated yet"}
          </span>
        )}
      </div>
      <div className="mt-3">
        <HealthReasons reasons={live?.reasons ?? resource.health_reasons} status={live?.status ?? resource.health_status} />
      </div>
    </WidgetFrame>
  );
}

export function AlertTableWidget({ widget, resource }: WidgetProps) {
  const query = useQuery({
    queryKey: ["alerts", { resource_id: resource.id, status: "open" }],
    queryFn: () => endpoints.alerts({ resource_id: resource.id, status: "open", page_size: 20 }),
  });
  return (
    <WidgetFrame title={widget.title} bodyClassName="px-0">
      {query.isLoading ? (
        <div className="px-4">
          <WidgetLoading height={60} />
        </div>
      ) : query.isError ? (
        <div className="px-4">
          <WidgetError error={query.error} />
        </div>
      ) : (
        <AlertTable alerts={query.data?.items ?? []} compact emptyMessage="No open alerts for this resource." />
      )}
    </WidgetFrame>
  );
}

export function ResourceTableWidget({ widget, resource }: WidgetProps) {
  const relation = configString(widget, "relation") ?? "children";
  const query = useQuery({
    queryKey: ["related", resource.id, relation],
    queryFn: () => endpoints.related(resource.id, relation),
  });
  return (
    <WidgetFrame title={widget.title} bodyClassName="px-0">
      {query.isLoading ? (
        <div className="px-4">
          <WidgetLoading height={60} />
        </div>
      ) : query.isError ? (
        <div className="px-4">
          <WidgetError error={query.error} />
        </div>
      ) : (query.data ?? []).length === 0 ? (
        <Unavailable message="No related resources have been discovered." />
      ) : (
        <Table>
          <THead>
            <TR>
              <TH>Name</TH>
              <TH>Type</TH>
              <TH>Region</TH>
              <TH>Health</TH>
            </TR>
          </THead>
          <tbody>
            {query.data?.map((r) => (
              <TR key={r.id}>
                <TD>
                  <Link to={`/resources/${r.id}`} className="font-medium hover:underline">
                    {r.name}
                  </Link>
                </TD>
                <TD>{r.type_display_name}</TD>
                <TD>{regionName(r.location)}</TD>
                <TD>
                  <HealthBadge status={r.health_status} />
                </TD>
              </TR>
            ))}
          </tbody>
        </Table>
      )}
    </WidgetFrame>
  );
}

export function PropertyCard({ widget, resource }: WidgetProps) {
  const property = configString(widget, "property") ?? "";
  const raw = resource.properties[property];
  const format = configString(widget, "format");
  const value =
    raw === undefined || raw === null || raw === ""
      ? null
      : format === "bytes" && typeof raw === "number"
        ? formatBytes(raw)
        : String(raw);
  return (
    <WidgetFrame title={widget.title}>
      {value === null ? (
        <Unavailable message="This property was not reported by Azure Resource Graph." />
      ) : (
        <div>
          <div className="truncate text-lg font-semibold" title={value}>
            {value}
          </div>
          <div className="text-xs text-muted-foreground">{configString(widget, "label") ?? property}</div>
        </div>
      )}
    </WidgetFrame>
  );
}

export function AppInsightsStatus({ widget, resource }: WidgetProps) {
  const relation = configString(widget, "relation") ?? "app_insights";
  const linkedId = resource.related[relation];
  const configured = relation in resource.related;
  return (
    <WidgetFrame title={widget.title}>
      {linkedId ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>This app sends telemetry to a linked Application Insights component.</span>
          <Link to={`/resources/${linkedId}`} className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
            Open Application Insights <ExternalLink className="size-3.5" />
          </Link>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {configured
            ? "The linked Application Insights component has not been discovered. Check that it is in a connected subscription."
            : "No Application Insights component is linked to this resource, so the telemetry below is not available."}
        </p>
      )}
    </WidgetFrame>
  );
}
