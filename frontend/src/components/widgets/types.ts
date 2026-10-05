import type { ComponentType } from "react";
import type { ResourceDetail, Widget } from "@/types/api";

export interface WidgetProps {
  widget: Widget;
  resource: ResourceDetail;
}

export type WidgetComponent = ComponentType<WidgetProps>;

export function configString(widget: Widget, key: string): string | undefined {
  const value = widget.config[key];
  return typeof value === "string" ? value : undefined;
}

export function configStrings(widget: Widget, key: string): string[] {
  const value = widget.config[key];
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}
