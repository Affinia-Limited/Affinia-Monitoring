import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { endpoints } from "@/api/endpoints";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useChartColors } from "@/hooks/useChartColors";
import { useFilters } from "@/stores/filters";
import type { ComparisonRow } from "@/types/api";
import { formatValue } from "@/utils/format";
import { timeRangeLabel, timeRangeParams } from "@/utils/timeRange";

function RowChart({ row, envs }: { row: ComparisonRow; envs: { id: string; name: string }[] }) {
  const colors = useChartColors();
  const data = [{ metric: row.label, ...Object.fromEntries(envs.map((e) => [e.name, row.values[e.id]])) }];
  return (
    <div className="h-40">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ left: 0, right: 8 }}>
          <CartesianGrid stroke={colors.grid} vertical={false} />
          <XAxis dataKey="metric" tick={{ fill: colors.axis, fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={(v: number) => formatValue(v, row.unit)} tick={{ fill: colors.axis, fontSize: 11 }} axisLine={false} tickLine={false} width={56} />
          <Tooltip
            formatter={(v) => formatValue(v as number, row.unit)}
            contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 6, fontSize: 12 }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" iconSize={8} />
          {envs.map((e, i) => (
            <Bar key={e.id} dataKey={e.name} fill={colors.palette[i % colors.palette.length]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function EnvironmentComparison({ projectId }: { projectId: string }) {
  const { timeRange } = useFilters();
  const params = timeRangeParams(timeRange);
  const query = useQuery({
    queryKey: ["comparison", projectId, params],
    queryFn: () => endpoints.comparison(projectId, params),
  });
  if (query.isLoading) return <LoadingBlock label="Comparing environments" />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const { environments, rows } = query.data;
  if (rows.length === 0) {
    return (
      <Card>
        <EmptyState title="Nothing to compare yet" description="Assign monitored resources to the environments of this project to compare them." />
      </Card>
    );
  }
  const highlight = rows.find((r) => r.metric === "plan_cpu") ?? rows[0];
  return (
    <div className="grid grid-cols-12 gap-4">
      <Card className="col-span-12 xl:col-span-8">
        <CardHeader title="Environment comparison" description={`${timeRangeLabel(timeRange)} - values combined across the resources in each environment`} />
        <CardContent className="px-0">
          <Table>
            <THead>
              <TR>
                <TH>Metric</TH>
                <TH>Resource type</TH>
                {environments.map((e) => (
                  <TH key={e.id} className="text-right">
                    {e.name}
                  </TH>
                ))}
              </TR>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TR key={`${r.monitor_key}-${r.metric}`}>
                  <TD className="font-medium">
                    {r.label}
                    <div className="text-xs text-muted-foreground">{r.rollup === "sum" ? "Total" : r.rollup === "max" ? "Peak" : "Average"}</div>
                  </TD>
                  <TD className="text-muted-foreground">{r.monitor_name}</TD>
                  {environments.map((e) => (
                    <TD key={e.id} className="tabular text-right" title={`${r.resource_counts[e.id] ?? 0} resources`}>
                      {r.values[e.id] === null || r.values[e.id] === undefined ? (
                        <span className="text-muted-foreground">-</span>
                      ) : (
                        formatValue(r.values[e.id], r.unit)
                      )}
                    </TD>
                  ))}
                </TR>
              ))}
            </tbody>
          </Table>
        </CardContent>
      </Card>
      <Card className="col-span-12 xl:col-span-4">
        <CardHeader title={highlight.label} description={highlight.monitor_name} />
        <CardContent>
          <RowChart row={highlight} envs={environments} />
        </CardContent>
      </Card>
    </div>
  );
}
