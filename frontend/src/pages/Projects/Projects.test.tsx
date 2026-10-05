import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AlertsExplorer } from "@/components/AlertsExplorer";
import { HealthSummary, healthScore } from "@/components/health";
import { ProjectCard } from "@/components/projects/ProjectCard";
import { counts, environment, project, resource } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { EnvironmentPage } from "./EnvironmentPage";
import { ProjectDetailPage } from "./ProjectDetailPage";
import { ProjectsPage } from "./ProjectsPage";

// Deliberately not "CRM"/"PRISM", and with a non-standard set of environments.
const alpha = project({
  id: "p-alpha",
  name: "Alpha Analytics",
  description: "Data platform",
  status: "warning",
  active_alerts: 2,
  health: counts({ healthy: 50, warning: 3, critical: 1 }),
  environments: [
    environment({ id: "a-dev", project_id: "p-alpha", name: "Development", health: counts({ healthy: 20 }), status: "healthy" }),
    environment({ id: "a-qa", project_id: "p-alpha", name: "QA", health: counts({ healthy: 12, warning: 1 }), status: "warning", active_alerts: 1 }),
    environment({ id: "a-stg", project_id: "p-alpha", name: "Staging", health: counts({ healthy: 8 }), status: "healthy" }),
    environment({
      id: "a-prod",
      project_id: "p-alpha",
      name: "Production",
      health: counts({ healthy: 10, warning: 2, critical: 1 }),
      status: "critical",
      active_alerts: 1,
      last_checked_at: "2026-10-06T09:58:00Z",
    }),
  ],
});
const beta = project({ id: "p-beta", name: "Beta Billing", environments: [environment({ id: "b-prod", project_id: "p-beta", health: counts({ healthy: 4 }) })], health: counts({ healthy: 4 }) });
const emptyFacets = { resource_types: [], locations: [], resource_groups: [], subscriptions: [], health: [] };

describe("ProjectCard", () => {
  it("renders whatever environments the project has, with status in words", () => {
    renderWithProviders(<ProjectCard project={alpha} />);
    const list = screen.getByRole("list", { name: "Alpha Analytics environments" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Development"),
      expect.stringContaining("QA"),
      expect.stringContaining("Staging"),
      expect.stringContaining("Production"),
    ]);
    expect(within(list).getByRole("link", { name: "QA" })).toHaveAttribute("href", "/projects/p-alpha/environments/a-qa");
    expect(within(list).getAllByText("Critical")).toHaveLength(1);
    expect(screen.getByText("4 environments")).toBeInTheDocument();
    expect(screen.getByText("2 active alerts")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View project Alpha Analytics" })).toHaveAttribute("href", "/projects/p-alpha");
  });
});

describe("HealthSummary", () => {
  it("shows the counts behind the score and ignores unchecked resources", () => {
    expect(healthScore(counts({ healthy: 30, warning: 2, critical: 2, unknown: 6 }))).toBe(88);
    expect(healthScore(counts({ unknown: 5 }))).toBeNull();
    renderWithProviders(<HealthSummary counts={counts({ healthy: 30, warning: 2, critical: 2 })} title="Production health" />);
    expect(screen.getByLabelText("88% healthy")).toBeInTheDocument();
    expect(screen.getByText("Warning").nextElementSibling).toHaveTextContent("2");
  });
});

describe("Projects page", () => {
  it("searches and filters projects without calling the API again", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/projects", () => {
        calls += 1;
        return HttpResponse.json([alpha, beta]);
      }),
    );
    renderWithProviders(<ProjectsPage />);
    expect(await screen.findByRole("link", { name: "Alpha Analytics" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search projects"), "billing");
    expect(screen.queryByRole("link", { name: "Alpha Analytics" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Beta Billing" })).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Search projects"));
    await userEvent.click(screen.getByRole("button", { name: /Needs attention/ }));
    expect(screen.getByRole("link", { name: "Alpha Analytics" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Beta Billing" })).not.toBeInTheDocument();
    expect(calls).toBe(1);
  });

  it("shows an empty state with an Add project action", async () => {
    server.use(http.get("*/api/v1/projects", () => HttpResponse.json([])));
    renderWithProviders(<ProjectsPage />);
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Add project/ }).length).toBeGreaterThan(0);
  });

  it("shows a friendly error with retry", async () => {
    let fail = true;
    server.use(
      http.get("*/api/v1/projects", () =>
        fail ? HttpResponse.json({ error: { code: "INTERNAL_ERROR", message: "An unexpected error occurred." } }, { status: 500 }) : HttpResponse.json([beta]),
      ),
    );
    renderWithProviders(<ProjectsPage />);
    expect(await screen.findByText("Unable to load projects.")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "Beta Billing" })).toBeInTheDocument();
  });
});

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      <Route path="/projects/:projectId/environments/:environmentId" element={<EnvironmentPage />} />
    </Routes>,
    { route },
  );
}

describe("Project detail page", () => {
  it("shows breadcrumbs, environment navigation, cards and a comparison table", async () => {
    server.use(
      http.get("*/api/v1/projects/p-alpha", () => HttpResponse.json(alpha)),
      http.get("*/api/v1/resources/facets", () =>
        HttpResponse.json({ ...emptyFacets, resource_types: [{ value: "microsoft.web/sites", label: "App Service", count: 8 }] }),
      ),
      http.get("*/api/v1/projects/p-alpha/comparison", () => HttpResponse.json({ project_id: "p-alpha", environments: [], rows: [], start: "", end: "", is_mock: false })),
    );
    renderAt("/projects/p-alpha");
    const crumbs = await screen.findByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Projects" })).toHaveAttribute("href", "/projects");
    const nav = screen.getByRole("navigation", { name: "Alpha Analytics sections" });
    expect(within(nav).getAllByRole("link").map((l) => l.textContent)).toEqual(["Overview", "Development", "QA", "Staging", "Production"]);
    expect(screen.getByRole("link", { name: "Open environment Staging" })).toHaveAttribute("href", "/projects/p-alpha/environments/a-stg");

    const table = screen.getByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Area", "Development", "QA", "Staging", "Production"]);
    const critical = within(table).getByRole("rowheader", { name: "Critical" }).closest("tr") as HTMLElement;
    expect(within(critical).getAllByRole("cell").map((c) => c.textContent)).toEqual(["0", "0", "0", "1"]);
    expect(await screen.findByText("App Service")).toBeInTheDocument();
  });

  it("redirects old ?environment= links to the environment page", async () => {
    server.use(
      http.get("*/api/v1/projects/p-alpha", () => HttpResponse.json(alpha)),
      http.get("*/api/v1/resources", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 8 })),
      http.get("*/api/v1/alerts", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 5 })),
    );
    renderAt("/projects/p-alpha?environment=a-qa");
    expect(await screen.findByRole("heading", { name: "Alpha Analytics / QA" })).toBeInTheDocument();
  });
});

describe("Environment page", () => {
  const critical = {
    ...resource,
    id: "r-crit",
    name: "app-alpha-prod",
    health_status: "critical" as const,
    active_alerts: 1,
    health_reasons: [{ signal: "metric" as const, severity: "critical" as const, message: "CPU", label: "CPU", unit: "percent", value: 96, operator: "gt", threshold: 90 }],
    health_metrics: [{ metric: "cpu", label: "CPU", unit: "percent", value: 96, status: "critical" as const, window_minutes: 15 }],
  };

  it("leads with the summary and only the issues that need attention", async () => {
    const seen: URLSearchParams[] = [];
    server.use(
      http.get("*/api/v1/projects/p-alpha", () => HttpResponse.json(alpha)),
      http.get("*/api/v1/resources", ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: [critical], total: 1, page: 1, page_size: 8 });
      }),
      http.get("*/api/v1/alerts", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 5 })),
    );
    renderAt("/projects/p-alpha/environments/a-prod");
    expect(await screen.findByRole("heading", { name: "Alpha Analytics / Production" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Alpha Analytics" })).toHaveAttribute("href", "/projects/p-alpha");
    expect(await screen.findByText("CPU 96%, above the critical threshold of 90%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View resource app-alpha-prod" })).toHaveAttribute("href", "/resources/r-crit");
    expect(screen.getByText(/No active alerts/)).toBeInTheDocument();
    const issues = seen.find((p) => p.get("health") === "critical,warning");
    expect(issues?.get("environment_id")).toBe("a-prod");
  });

  it("says so plainly when nothing needs attention", async () => {
    server.use(
      http.get("*/api/v1/projects/p-alpha", () => HttpResponse.json(alpha)),
      http.get("*/api/v1/resources", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 8 })),
      http.get("*/api/v1/alerts", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 5 })),
    );
    renderAt("/projects/p-alpha/environments/a-dev");
    expect(await screen.findByText("No critical issues")).toBeInTheDocument();
    expect(screen.getByText("Everything looks healthy.")).toBeInTheDocument();
  });

  it("filters the resource table on the server and shows the key metric", async () => {
    const seen: URLSearchParams[] = [];
    server.use(
      http.get("*/api/v1/projects/p-alpha", () => HttpResponse.json(alpha)),
      http.get("*/api/v1/resources/facets", () =>
        HttpResponse.json({ ...emptyFacets, health: [{ value: "critical", label: "Critical", count: 1 }] }),
      ),
      http.get("*/api/v1/resources", ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: [critical], total: 1, page: 1, page_size: 25 });
      }),
    );
    renderAt("/projects/p-alpha/environments/a-prod?tab=resources");
    const table = await screen.findByRole("table");
    const row = within(table).getByRole("link", { name: "app-alpha-prod" }).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("CPU 96%");
    expect(row).toHaveTextContent("Critical");
    await userEvent.click(screen.getByRole("button", { name: /^Critical/ }));
    await userEvent.type(screen.getByLabelText("Search resources"), "app");
    await waitFor(() => {
      const last = seen[seen.length - 1];
      expect(last.get("health")).toBe("critical");
      expect(last.get("q")).toBe("app");
      expect(last.get("environment_id")).toBe("a-prod");
      expect(last.get("monitored_only")).toBe("true");
    });
  });

  it("handles an environment that no longer exists", async () => {
    server.use(http.get("*/api/v1/projects/p-alpha", () => HttpResponse.json(alpha)));
    renderAt("/projects/p-alpha/environments/missing");
    expect(await screen.findByText("Environment not found")).toBeInTheDocument();
  });
});

describe("Alerts explorer", () => {
  it("sends severity, type, time and search filters to the API", async () => {
    const seen: URLSearchParams[] = [];
    server.use(
      http.get("*/api/v1/resources/monitors", () => HttpResponse.json([{ key: "app_service", display_name: "App Service", category: "Compute", resource_types: [], metrics: [] }])),
      http.get("*/api/v1/alerts", ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 });
      }),
    );
    renderWithProviders(<AlertsExplorer projectId="p-alpha" environmentId="a-prod" onSelect={() => {}} />);
    expect(await screen.findByText("No active alerts")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Critical" }));
    await userEvent.selectOptions(await screen.findByLabelText("Resource type"), "app_service");
    await userEvent.selectOptions(screen.getByLabelText("Time"), "24");
    await userEvent.type(screen.getByLabelText("Search alerts"), "cpu");
    await waitFor(() => {
      const last = seen[seen.length - 1];
      expect(Object.fromEntries(last)).toMatchObject({
        status: "open",
        severity: "critical",
        project_id: "p-alpha",
        environment_id: "a-prod",
        monitor_key: "app_service",
        since_hours: "24",
        q: "cpu",
      });
    });
    expect(screen.getByText("No alerts match these filters")).toBeInTheDocument();
  });
});
