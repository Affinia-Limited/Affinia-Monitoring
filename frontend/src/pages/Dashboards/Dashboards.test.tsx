import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { LogBar, LogPie, LogStat, Note } from "@/components/widgets/LogInsightWidgets";
import { LogTable } from "@/components/widgets/LogWidgets";
import { resource } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { DashboardSummary, LogQueryResult, Widget } from "@/types/api";
import { DashboardsPage } from "./DashboardsPage";

function summary(id: string, name: string, project: string | null, env: string | null, order: number | null, tags: string[]): DashboardSummary {
  return {
    id,
    name,
    description: "",
    kind: "resource",
    resource_id: `r-${id}`,
    template_version: 3,
    is_customized: false,
    updated_at: "2026-10-05T10:00:00Z",
    resource_type: "microsoft.web/sites",
    type_display_name: "App Service",
    project_name: project,
    environment_name: env,
    environment_order: order,
    health_status: "healthy",
    tags,
  };
}

const DASHBOARDS = [
  summary("1", "app-alpha-prod", "Alpha", "Production", 2, ["azure", "app-service", "alpha", "prod"]),
  summary("2", "app-alpha-dev", "Alpha", "Development", 0, ["azure", "app-service", "alpha", "dev"]),
  summary("3", "sql-alpha-dev", "Alpha", "Development", 0, ["azure", "azure-sql-database", "alpha", "dev"]),
  summary("4", "app-beta-uat", "Beta", "UAT", 1, ["azure", "app-service", "beta", "uat"]),
  summary("5", "kv-loose", null, null, null, ["azure", "key-vault"]),
];

function rowNames(): string[] {
  return screen.getAllByRole("link").map((l) => l.textContent ?? "");
}

describe("Dashboards page", () => {
  it("groups dashboards into project folders with environment subfolders in project order", async () => {
    server.use(http.get("*/api/v1/dashboards", () => HttpResponse.json(DASHBOARDS)));
    renderWithProviders(<DashboardsPage />);
    expect(await screen.findByRole("button", { name: /^Alpha/ })).toHaveAttribute("aria-expanded", "true");
    const folders = screen.getAllByRole("button", { expanded: true }).map((b) => b.textContent);
    // Development (order 0) before Production (order 2), whatever the alphabet says.
    expect(folders).toEqual(["Alpha3", "Development2", "Production1", "Beta1", "UAT1"]);
    // Unassigned starts closed.
    expect(screen.getByRole("button", { name: /^Unassigned/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "kv-loose" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Alpha/ }));
    expect(screen.queryByRole("link", { name: "app-alpha-dev" })).not.toBeInTheDocument();
  });

  it("filters by search and by tag, opening folders that contain matches", async () => {
    server.use(http.get("*/api/v1/dashboards", () => HttpResponse.json(DASHBOARDS)));
    renderWithProviders(<DashboardsPage />);
    await screen.findByRole("link", { name: "app-alpha-prod" });
    await userEvent.type(screen.getByLabelText("Search dashboards"), "loose");
    expect(rowNames()).toEqual(["kv-loose"]);
    await userEvent.clear(screen.getByLabelText("Search dashboards"));

    const row = screen.getByRole("link", { name: "app-beta-uat" }).closest('[role="row"]') as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "uat" }));
    expect(rowNames()).toEqual(["app-beta-uat"]);
    await userEvent.click(screen.getByRole("button", { name: /Clear/ }));
    expect(rowNames()).toHaveLength(4);
  });

  it("stars dashboards in this browser and shows only starred ones", async () => {
    window.localStorage.removeItem("amp.dashboards.starred");
    server.use(http.get("*/api/v1/dashboards", () => HttpResponse.json(DASHBOARDS)));
    renderWithProviders(<DashboardsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Star app-alpha-dev" }));
    await userEvent.click(screen.getByLabelText("Starred"));
    expect(rowNames()).toEqual(["app-alpha-dev"]);
    expect(JSON.parse(window.localStorage.getItem("amp.dashboards.starred") ?? "[]")).toEqual(["2"]);
  });

  it("has a flat list view that shows each dashboard's location", async () => {
    server.use(http.get("*/api/v1/dashboards", () => HttpResponse.json(DASHBOARDS)));
    renderWithProviders(<DashboardsPage />);
    await screen.findByRole("link", { name: "app-alpha-prod" });
    await userEvent.click(screen.getByRole("button", { name: "List view" }));
    expect(rowNames()).toHaveLength(5);
    expect(screen.getByText("Alpha / Production")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "-name");
    expect(rowNames()[0]).toBe("sql-alpha-dev");
  });
});

function logResult(columns: [string, string][], rows: unknown[][]): LogQueryResult {
  return {
    resource_id: "r1",
    executed_against: "r1",
    query: "",
    columns: columns.map(([name, type]) => ({ name, type })),
    rows,
    row_count: rows.length,
    truncated: false,
    partial_error: null,
    visualization: "table",
    is_mock: false,
    start: "2026-10-05T00:00:00Z",
    end: "2026-10-05T12:00:00Z",
  } as LogQueryResult;
}

function widget(type: string, title: string, config: Record<string, unknown>): Widget {
  return { id: "w", position: 0, section: "Service health", widget_type: type, title, width: 2, config };
}

describe("Log widgets", () => {
  it("shows a headline value from the named field", async () => {
    server.use(
      http.post("*/api/v1/logs/query", () =>
        HttpResponse.json(logResult([["Satisfied", "long"], ["Tolerating", "long"], ["Total", "long"], ["Apdex", "real"]], [[90, 8, 100, 0.94]])),
      ),
    );
    renderWithProviders(<LogStat widget={widget("log_stat", "Apdex", { query: "sli_apdex", unit: "none", field: "Apdex" })} resource={resource} />);
    expect(await screen.findByLabelText(/Apdex: /)).toHaveTextContent("0.94");
  });

  it("formats percentages and falls back to the last numeric column", async () => {
    server.use(http.post("*/api/v1/logs/query", () => HttpResponse.json(logResult([["Availability", "real"]], [[99.912]]))));
    renderWithProviders(<LogStat widget={widget("log_stat", "Availability", { query: "sli_availability", unit: "percent" })} resource={resource} />);
    expect(await screen.findByText("100%")).toBeInTheDocument();
  });

  it("explains how to enable logs instead of showing an error", async () => {
    server.use(
      http.post("*/api/v1/logs/query", () =>
        HttpResponse.json(
          { error: { code: "LOG_TABLE_NOT_FOUND", message: "No logs of this kind yet. Enable Diagnostic settings for this resource." } },
          { status: 400 },
        ),
      ),
    );
    renderWithProviders(<LogTable widget={widget("log_table", "Endpoint performance", { query: "endpoint_performance" })} resource={resource} />);
    expect(await screen.findByText(/Enable Diagnostic settings/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("draws a success vs failure donut with percentages", async () => {
    server.use(http.post("*/api/v1/logs/query", () => HttpResponse.json(logResult([["Success", "long"], ["Failed", "long"]], [[950, 50]]))));
    renderWithProviders(<LogPie widget={widget("log_pie", "Request success vs failure", { query: "success_vs_failure" })} resource={resource} />);
    expect(await screen.findByText("95.0%")).toBeInTheDocument();
    expect(screen.getByText("5.0%")).toBeInTheDocument();
  });

  it("renders category bars", async () => {
    server.use(http.post("*/api/v1/logs/query", () => HttpResponse.json(logResult([["Status", "string"], ["Requests", "long"]], [["200", 900], ["404", 40]]))));
    renderWithProviders(<LogBar widget={widget("log_bar", "Status code distribution", { query: "status_code_distribution" })} resource={resource} />);
    expect(await screen.findByTestId("log-bar-chart")).toBeInTheDocument();
  });

  it("renders section notes as headings", () => {
    renderWithProviders(<Note widget={widget("note", "Latency", { text: "Percentiles rather than averages." })} resource={resource} />);
    expect(screen.getByRole("heading", { name: "Latency" })).toBeInTheDocument();
    expect(screen.getByText("Percentiles rather than averages.")).toBeInTheDocument();
  });
});
