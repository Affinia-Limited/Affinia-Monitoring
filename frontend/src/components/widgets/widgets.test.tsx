import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { metric, resource, viewer, widget } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { Dashboard, WidgetIn } from "@/types/api";
import { formatAxisTime, formatAxisValue } from "@/utils/format";
import { Gauge, MetricCard } from "./MetricWidgets";
import { ResourceDashboard } from "./ResourceDashboard";
import { levelColour, thresholdLevel } from "./thresholds";

function metricsHandler(value: number, unit = "percent") {
  return http.get("*/api/v1/resources/r1/metrics", ({ request }) => {
    const key = new URL(request.url).searchParams.get("metrics") ?? "m";
    return HttpResponse.json({
      resource_id: "r1",
      start: "",
      end: "",
      metrics: [metric({ key, unit, summary: { avg: value, max: value, min: value, sum: value, latest: value } })],
    });
  });
}

describe("threshold levels", () => {
  it("treats 'lt' rules as lower-is-worse", () => {
    const t = { operator: "lt" as const, warning: 90, critical: 50 };
    expect(thresholdLevel(100, t)).toBe("healthy");
    expect(thresholdLevel(75, t)).toBe("warning");
    expect(thresholdLevel(40, t)).toBe("critical");
  });

  it("treats 'gt' rules as higher-is-worse", () => {
    const t = { operator: "gt" as const, warning: 80, critical: 90 };
    expect(thresholdLevel(35, t)).toBe("healthy");
    expect(thresholdLevel(85, t)).toBe("warning");
    expect(thresholdLevel(94, t)).toBe("critical");
  });

  it("is neutral without thresholds", () => {
    expect(thresholdLevel(100, null)).toBeNull();
    expect(levelColour(null)).toBe("var(--primary)");
  });
});

describe("Gauge colouring", () => {
  it("colours Front Door origin health at 100% as healthy, not red", async () => {
    server.use(metricsHandler(100));
    renderWithProviders(
      <Gauge
        resource={resource}
        widget={widget({ widget_type: "gauge", title: "Origin health", config: { metric: "origin_health", thresholds: { operator: "lt", warning: 90, critical: 50 } } })}
      />,
    );
    const arc = await screen.findByTestId("gauge-arc");
    expect(arc).toHaveAttribute("data-level", "healthy");
    expect(arc).toHaveAttribute("stroke", "var(--status-healthy)");
  });

  it("colours a breached critical threshold red", async () => {
    server.use(metricsHandler(95));
    renderWithProviders(
      <Gauge resource={resource} widget={widget({ widget_type: "gauge", title: "CPU", config: { metric: "plan_cpu", thresholds: { operator: "gt", warning: 80, critical: 90 } } })} />,
    );
    expect(await screen.findByTestId("gauge-arc")).toHaveAttribute("stroke", "var(--status-critical)");
  });

  it("uses the neutral colour when the metric has no health rule", async () => {
    server.use(metricsHandler(99));
    renderWithProviders(<Gauge resource={resource} widget={widget({ widget_type: "gauge", title: "Storage", config: { metric: "storage_percent" } })} />);
    const arc = await screen.findByTestId("gauge-arc");
    expect(arc).toHaveAttribute("data-level", "none");
    expect(arc).toHaveAttribute("stroke", "var(--primary)");
  });

  it("colours metric card values that breach a threshold", async () => {
    server.use(metricsHandler(85));
    renderWithProviders(
      <MetricCard resource={resource} widget={widget({ title: "CPU", config: { metric: "plan_cpu", thresholds: { operator: "gt", warning: 80, critical: 90 } } })} />,
    );
    expect(await screen.findByLabelText("CPU")).toHaveAttribute("data-level", "warning");
  });
});

describe("axis formatting", () => {
  it("formats time ticks by span", () => {
    const t = new Date(2026, 8, 30, 14, 5).getTime();
    expect(formatAxisTime(t, 3600_000)).toBe("14:05");
    expect(formatAxisTime(t, 3 * 24 * 3600_000)).toBe("30/09 14:05");
    expect(formatAxisTime(t, 30 * 24 * 3600_000)).toBe("30/09");
  });

  it("formats compact value ticks with units", () => {
    expect(formatAxisValue(40, "percent")).toBe("40%");
    expect(formatAxisValue(120, "milliseconds")).toBe("120 ms");
    expect(formatAxisValue(12000, "count")).toBe("12K");
    expect(formatAxisValue(1536, "bytes")).toBe("1.5 KB");
  });
});

const dashboard: Dashboard = {
  id: "d1",
  name: "app-crm-prod-uks",
  description: "App Service dashboard",
  kind: "resource",
  resource_id: "r1",
  template_version: 2,
  is_customized: false,
  updated_at: "2026-09-30T10:00:00Z",
  resource_type: "microsoft.web/sites",
  type_display_name: "App Service",
  project_name: "CRM",
  environment_name: "Production",
  health_status: "healthy",
  sections: ["Overview", "HTTP"],
  widgets: [
    { id: "w1", position: 0, section: "Overview", widget_type: "property_card", title: "Instances", width: 4, config: { property: "skuCapacity" } },
    { id: "w2", position: 1, section: "Overview", widget_type: "resource_health", title: "Health", width: 4, config: {} },
    { id: "w3", position: 2, section: "Overview", widget_type: "property_card", title: "Plan", width: 4, config: { property: "serverFarmId" } },
    { id: "w4", position: 3, section: "HTTP", widget_type: "property_card", title: "Host", width: 12, config: { property: "defaultHostName" } },
  ],
};

describe("dashboard customisation", () => {
  it("edits widgets and saves the full ordered list", async () => {
    let saved: { widgets: WidgetIn[] } | null = null;
    server.use(
      http.get("*/api/v1/resources/r1/metric-definitions", () =>
        HttpResponse.json([
          { key: "requests", label: "Requests", unit: "count", aggregation: "Total", split_by: null, target: "self", description: "" },
          { key: "requests_by_status", label: "By status", unit: "count", aggregation: "Total", split_by: "HttpStatusGroup", target: "self", description: "" },
        ]),
      ),
      http.patch("*/api/v1/dashboards/d1", async ({ request }) => {
        saved = (await request.json()) as { widgets: WidgetIn[] };
        return HttpResponse.json({ ...dashboard, is_customized: true });
      }),
      http.get("*/api/v1/resources/r1/metrics", () => HttpResponse.json({ resource_id: "r1", start: "", end: "", metrics: [] })),
    );
    const user = userEvent.setup();
    renderWithProviders(<ResourceDashboard dashboard={dashboard} resource={resource} />);

    await user.click(await screen.findByRole("button", { name: "Dashboard options" }));
    await user.click(await screen.findByRole("menuitem", { name: /Customise/ }));
    expect(screen.getAllByTestId("editable-widget")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "Remove Health" }));
    await user.selectOptions(screen.getByLabelText("Width of Instances"), "6");
    await user.click(screen.getByRole("button", { name: "Move Plan up" }));

    await user.click(screen.getByRole("button", { name: "Add line chart" }));
    const dialog = await screen.findByRole("dialog");
    // Split metrics are not offered.
    expect(within(dialog).queryByText("By status")).not.toBeInTheDocument();
    await user.click(await within(dialog).findByLabelText(/Requests/));
    await user.click(within(dialog).getByRole("button", { name: "Add chart" }));

    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Customised");

    expect(saved).not.toBeNull();
    const widgets = saved!.widgets;
    expect(widgets.map((w) => w.title)).toEqual(["Plan", "Instances", "Requests", "Host"]);
    expect(widgets[1]).toMatchObject({ width: 6 });
    expect(widgets[2]).toMatchObject({ section: "Overview", widget_type: "line_chart", config: { metrics: ["requests"] } });
    expect(widgets[3]).toMatchObject({ section: "HTTP" });
  });

  it("resets a customised dashboard after confirmation", async () => {
    let resetCalled = false;
    server.use(
      http.post("*/api/v1/dashboards/d1/reset", () => {
        resetCalled = true;
        return HttpResponse.json({ ...dashboard, is_customized: false });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ResourceDashboard dashboard={{ ...dashboard, is_customized: true }} resource={resource} />);
    expect(await screen.findByText("Customised")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Dashboard options" }));
    await user.click(await screen.findByRole("menuitem", { name: /Reset to template/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Reset to template" }));
    await vi.waitFor(() => expect(resetCalled).toBe(true));
  });

  it("hides customisation from users without dashboards:manage", async () => {
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)));
    renderWithProviders(<ResourceDashboard dashboard={dashboard} resource={resource} />);
    expect(await screen.findByText("Instances")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dashboard options" })).not.toBeInTheDocument();
  });
});
