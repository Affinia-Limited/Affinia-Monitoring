import { LogChart, DependencyMap, LogTable } from "./LogWidgets";
import { AreaChartWidget, BarChartWidget, Gauge, LineChartWidget, MetricCard } from "./MetricWidgets";
import {
  AlertTableWidget,
  AppInsightsStatus,
  PropertyCard,
  ResourceHealthCard,
  ResourceTableWidget,
} from "./ResourceWidgets";
import type { WidgetComponent, WidgetProps } from "./types";
import { WidgetFrame } from "./WidgetFrame";

/** widget_type (from backend dashboard templates) -> component. */
export const WIDGET_REGISTRY: Record<string, WidgetComponent> = {
  metric_card: MetricCard,
  gauge: Gauge,
  line_chart: LineChartWidget,
  area_chart: AreaChartWidget,
  bar_chart: BarChartWidget,
  resource_health: ResourceHealthCard,
  alert_table: AlertTableWidget,
  log_table: LogTable,
  log_chart: LogChart,
  resource_table: ResourceTableWidget,
  property_card: PropertyCard,
  app_insights_status: AppInsightsStatus,
  dependency_map: DependencyMap,
};

export function UnknownWidget({ widget }: WidgetProps) {
  return (
    <WidgetFrame title={widget.title}>
      <p className="text-sm text-muted-foreground">This widget type ({widget.widget_type}) is not supported by this version of the UI.</p>
    </WidgetFrame>
  );
}

export function resolveWidget(type: string): WidgetComponent {
  return WIDGET_REGISTRY[type] ?? UnknownWidget;
}
