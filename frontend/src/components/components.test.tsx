import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { alert, metric, resource, widget } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { AlertTable } from "./AlertTable";
import { ConfirmButton } from "./common";
import { EnvironmentResourceTable } from "./EnvironmentResourceTable";
import { HealthBadge } from "./status";
import { DashboardRenderer } from "./widgets/DashboardRenderer";
import { MetricCard, MetricValue } from "./widgets/MetricWidgets";

describe("HealthBadge", () => {
  it.each([
    ["healthy", "Healthy"],
    ["warning", "Warning"],
    ["critical", "Critical"],
    ["unknown", "Unknown"],
  ])("renders %s", (status, label) => {
    renderWithProviders(<HealthBadge status={status} />);
    expect(screen.getByTestId("health-badge")).toHaveTextContent(label);
  });

  it("treats unexpected values as unknown", () => {
    renderWithProviders(<HealthBadge status="bogus" />);
    expect(screen.getByTestId("health-badge")).toHaveTextContent("Unknown");
  });
});

describe("MetricCard", () => {
  it("shows the reduced value", () => {
    renderWithProviders(<MetricValue metric={metric()} reducer="avg" title="CPU" />);
    expect(screen.getByLabelText("CPU")).toHaveTextContent("35%");
  });

  it("shows the unavailable state instead of a value", () => {
    renderWithProviders(
      <MetricValue
        metric={metric({ series: [], summary: {}, unavailable_reason: "NO_DATA", unavailable_message: "Azure returned no data for this metric." })}
        reducer="avg"
      />,
    );
    expect(screen.getByText("Not available for this resource")).toBeInTheDocument();
    expect(screen.getByText("Azure returned no data for this metric.")).toBeInTheDocument();
  });

  it("fetches its metric from the API", async () => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/resources/r1/metrics", ({ request }) => {
        seen(new URL(request.url).searchParams.get("metrics"));
        return HttpResponse.json({ resource_id: "r1", start: "", end: "", metrics: [metric({ key: "requests", unit: "count", summary: { sum: 12481 } })] });
      }),
    );
    renderWithProviders(<MetricCard widget={widget({ title: "Requests", config: { metric: "requests", reducer: "sum" } })} resource={resource} />);
    expect(await screen.findByText("12.5K")).toBeInTheDocument();
    expect(seen).toHaveBeenCalledWith("requests");
  });
});

describe("DashboardRenderer", () => {
  it("renders widgets by type and batches metric keys per widget", async () => {
    const requested: string[] = [];
    server.use(
      http.get("*/api/v1/resources/r1/metrics", ({ request }) => {
        const keys = new URL(request.url).searchParams.get("metrics") ?? "";
        requested.push(keys);
        return HttpResponse.json({ resource_id: "r1", start: "", end: "", metrics: keys.split(",").map((key) => metric({ key })) });
      }),
    );
    renderWithProviders(
      <DashboardRenderer
        resource={resource}
        widgets={[
          widget({ id: "1", position: 0, widget_type: "metric_card", title: "CPU", config: { metric: "plan_cpu" } }),
          widget({ id: "2", position: 1, widget_type: "line_chart", title: "CPU and memory", width: 8, config: { metrics: ["plan_cpu", "plan_memory"] } }),
          widget({ id: "3", position: 2, widget_type: "resource_health", title: "Health", width: 4 }),
          widget({ id: "4", position: 3, widget_type: "future_widget", title: "Future" }),
        ]}
      />,
    );
    const grid = screen.getByTestId("dashboard-grid");
    expect(grid.querySelectorAll("[data-widget-type]")).toHaveLength(4);
    expect(await screen.findByLabelText("CPU")).toHaveTextContent("35%");
    expect(screen.getByText("Health")).toBeInTheDocument();
    expect(screen.getByText(/not supported by this version/)).toBeInTheDocument();
    await vi.waitFor(() => expect(requested).toContain("plan_cpu,plan_memory"));
  });
});

describe("AlertTable", () => {
  it("renders alert columns and handles selection", async () => {
    const onSelect = vi.fn();
    renderWithProviders(<AlertTable alerts={[alert()]} onSelect={onSelect} />);
    const row = screen.getByText("Plan CPU > 90 on app-crm-prod-uks").closest("tr") as HTMLElement;
    expect(within(row).getByText("Critical")).toBeInTheDocument();
    expect(within(row).getByText("CRM")).toBeInTheDocument();
    expect(within(row).getByText("Production")).toBeInTheDocument();
    expect(within(row).getByText("94%")).toBeInTheDocument();
    expect(within(row).getByText("> 90%")).toBeInTheDocument();
    expect(within(row).getByText("10 minutes ago")).toBeInTheDocument();
    expect(within(row).getByText("Active")).toBeInTheDocument();
    await userEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "a1" }));
  });

  it("shows an empty state", () => {
    renderWithProviders(<AlertTable alerts={[]} emptyMessage="No active alerts." />);
    expect(screen.getByText("No active alerts.")).toBeInTheDocument();
  });
});

describe("ConfirmButton", () => {
  it("keeps the dialog open and explains a failed action", async () => {
    const onConfirm = vi.fn(async () => {
      throw new ApiError(409, { code: "CONFLICT", message: "The project still has environments.", request_id: "req-1" });
    });
    renderWithProviders(
      <ConfirmButton title="Delete project?" description="This cannot be undone." confirmLabel="Delete" onConfirm={onConfirm}>
        Delete project
      </ConfirmButton>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The project still has environments.");
    expect(within(dialog).getByRole("button", { name: "Delete" })).toBeEnabled();
  });
});

describe("EnvironmentResourceTable paging", () => {
  it("returns to the last page when the total shrinks", async () => {
    let total = 30;
    server.use(
      http.get("*/api/v1/resources", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page"));
        const items = page === 1 ? [resource] : total > 25 ? [{ ...resource, id: "r26", name: "page-two" }] : [];
        return HttpResponse.json({ items, total, page, page_size: 25 });
      }),
      http.get("*/api/v1/resources/facets", () => HttpResponse.json({ health: [], resource_types: [], locations: [], resource_groups: [], subscriptions: [] })),
    );
    renderWithProviders(<EnvironmentResourceTable projectId="p1" environmentId="e1" />);
    await screen.findByText("Page 1 of 2");
    total = 3;
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 1 of 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "app-crm-prod-uks" })).toBeInTheDocument();
  });
});
