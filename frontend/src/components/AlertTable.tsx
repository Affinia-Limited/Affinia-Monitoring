import { Link } from "react-router-dom";
import type { Alert } from "@/types/api";
import { formatDateTime, formatValue } from "@/utils/format";
import { AlertStatusBadge, SeverityBadge, TimeAgo } from "./status";
import { EmptyState } from "./ui/states";
import { LG_ONLY, Table, TD, TH, THead, TR } from "./ui/table";

const OPERATORS: Record<string, string> = { gt: ">", gte: ">=", lt: "<", lte: "<=" };

export function AlertTable({
  alerts,
  onSelect,
  compact = false,
  emptyMessage = "No alerts.",
}: {
  alerts: Alert[];
  onSelect?: (alert: Alert) => void;
  compact?: boolean;
  emptyMessage?: string;
}) {
  if (alerts.length === 0) return <EmptyState title={emptyMessage} className="py-6" />;
  return (
    <Table>
      <THead>
        <TR>
          <TH>Severity</TH>
          <TH>Alert</TH>
          {!compact ? <TH>Project</TH> : null}
          {!compact ? <TH className="hidden md:table-cell">Environment</TH> : null}
          <TH>Resource</TH>
          <TH>Metric</TH>
          <TH className="text-right">Current</TH>
          <TH className={`text-right ${LG_ONLY}`}>Threshold</TH>
          <TH>Started</TH>
          <TH>Status</TH>
        </TR>
      </THead>
      <tbody>
        {alerts.map((a) => (
          <TR
            key={a.id}
            className={onSelect ? "cursor-pointer hover:bg-muted/50" : undefined}
            onClick={onSelect ? () => onSelect(a) : undefined}
            tabIndex={onSelect ? 0 : undefined}
            onKeyDown={onSelect ? (e) => e.key === "Enter" && onSelect(a) : undefined}
          >
            <TD>
              <SeverityBadge severity={a.severity} />
            </TD>
            <TD className="max-w-48 truncate font-medium lg:max-w-72" title={a.title}>
              {a.title}
            </TD>
            {!compact ? <TD>{a.project_name ?? "-"}</TD> : null}
            {!compact ? <TD className="hidden md:table-cell">{a.environment_name ?? "-"}</TD> : null}
            <TD>
              <Link to={`/resources/${a.resource_id}`} className="hover:underline" onClick={(e) => e.stopPropagation()}>
                {a.resource_name ?? "Resource"}
              </Link>
              {a.type_display_name ? <div className="hidden text-xs text-muted-foreground lg:block">{a.type_display_name}</div> : null}
            </TD>
            <TD>{a.metric_name ?? "-"}</TD>
            <TD className="tabular text-right whitespace-nowrap">
              {a.current_value === null ? "-" : formatValue(a.current_value, a.unit ?? "")}
              {a.threshold !== null ? (
                <div className="text-xs text-muted-foreground lg:hidden">
                  Threshold {OPERATORS[a.operator ?? ""] ?? ""} {formatValue(a.threshold, a.unit ?? "")}
                </div>
              ) : null}
            </TD>
            <TD className={`tabular text-right whitespace-nowrap ${LG_ONLY}`}>
              {a.threshold === null ? "-" : `${OPERATORS[a.operator ?? ""] ?? ""} ${formatValue(a.threshold, a.unit ?? "")}`}
            </TD>
            <TD className="whitespace-nowrap">
              <TimeAgo value={a.started_at} />
              <div className="hidden text-xs text-muted-foreground lg:block">{formatDateTime(a.started_at)}</div>
            </TD>
            <TD>
              <AlertStatusBadge status={a.status} />
            </TD>
          </TR>
        ))}
      </tbody>
    </Table>
  );
}
