import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ResourceDetailPage } from "@/pages/Resources/ResourceDetailPage";
import { me, resource, viewer } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { GlobalSearch } from "./GlobalSearch";
import { Sidebar } from "./Sidebar";

describe("Sidebar", () => {
  it("shows administration items only to roles that may use them", async () => {
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)));
    renderWithProviders(<Sidebar collapsed={false} />);
    expect(await screen.findByText("Viewer")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit log" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Logs" })).not.toBeInTheDocument();
  });

  it("gives Super Admins the full administration section and an alert count", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () => HttpResponse.json(me({ display_name: "Aditya Kumar" }))),
      http.get("*/api/v1/alerts", () => HttpResponse.json({ items: [], total: 7, page: 1, page_size: 1 })),
    );
    renderWithProviders(<Sidebar collapsed={false} />);
    expect(await screen.findByText("Aditya Kumar")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/settings/users");
    expect(screen.getByRole("link", { name: "Audit log" })).toHaveAttribute("href", "/settings?tab=audit");
    expect(await screen.findByLabelText("7 open alerts")).toBeInTheDocument();
  });
});

describe("Sidebar filters", () => {
  it("keeps the chosen project, environment and time range when moving between pages", async () => {
    renderWithProviders(<Sidebar collapsed={false} />, { route: "/resources?project=p1&env=e1&range=7d&view=attention" });
    expect(await screen.findByRole("link", { name: "Alerts" })).toHaveAttribute("href", "/alerts?project=p1&env=e1&range=7d");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/?project=p1&env=e1&range=7d");
    // Administration pages have no global filters; page-specific parameters (view) are not carried.
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });
});

describe("Global search", () => {
  it("shows where every result lives", async () => {
    server.use(
      http.get("*/api/v1/search", () =>
        HttpResponse.json({
          query: "alpha-prod",
          hits: [
            { kind: "environment", id: "e1", title: "Alpha / Production", subtitle: "Environment", url: "/projects/p1/environments/e1" },
            {
              kind: "resource",
              id: "r1",
              title: "app-alpha-prod",
              subtitle: "App Service - Alpha / Production",
              url: "/resources/r1",
              health_status: "warning",
              project_name: "Alpha",
              environment_name: "Production",
              type_display_name: "App Service",
            },
            { kind: "logs", id: "logs-e1", title: "Logs for Alpha / Production", subtitle: "Log queries", url: "/logs?project=p1&env=e1" },
          ],
        }),
      ),
    );
    renderWithProviders(<GlobalSearch />);
    await userEvent.type(screen.getByRole("combobox"), "alpha-prod");
    const list = await screen.findByRole("listbox");
    expect(await within(list).findByText("Environments")).toBeInTheDocument();
    expect(within(list).getByText("Alpha · Production · App Service · Warning")).toBeInTheDocument();
    expect(within(list).getByText("Logs for Alpha / Production")).toBeInTheDocument();
  });
});

describe("Resource detail", () => {
  it("shows the full context trail and the type-specific key metrics", async () => {
    server.use(
      http.get("*/api/v1/resources/r1", () =>
        HttpResponse.json({
          ...resource,
          health_metrics: [
            { metric: "cpu", label: "CPU", unit: "percent", value: 23, status: "healthy", window_minutes: 15 },
            { metric: "response_time", label: "Response time", unit: "milliseconds", value: 420, status: "warning", window_minutes: 15 },
          ],
        }),
      ),
      http.get("*/api/v1/dashboards/by-resource/r1", () => HttpResponse.json({ error: { code: "NOT_FOUND", message: "No dashboard." } }, { status: 404 })),
    );
    renderWithProviders(
      <Routes>
        <Route path="/resources/:resourceId" element={<ResourceDetailPage />} />
      </Routes>,
      { route: "/resources/r1" },
    );
    const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getAllByRole("listitem").map((li) => li.textContent).filter(Boolean)).toEqual([
      "Projects",
      "CRM",
      "Production",
      "App Service",
      "app-crm-prod-uks",
    ]);
    expect(within(crumbs).getByRole("link", { name: "Production" })).toHaveAttribute("href", "/projects/p1/environments/e1");
    const metrics = screen.getByRole("region", { name: "Key metrics" });
    expect(within(metrics).getByText("23%")).toBeInTheDocument();
    expect(within(metrics).getByText("Response time").parentElement).toHaveTextContent("warning");
  });
});
