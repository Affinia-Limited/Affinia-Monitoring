import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { sortResources } from "@/components/ResourcesTable";
import { resource as base, project as makeProject, viewer } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { HealthStatus, Project, Resource } from "@/types/api";
import { OverviewPage } from "../Dashboard/OverviewPage";
import { ResourcesPage } from "./ResourcesPage";

function res(id: string, name: string, health: HealthStatus): Resource {
  return { ...base, id, name, health_status: health, project_id: null, project_name: null, environment_id: null, environment_name: null };
}

const items = [res("1", "b-healthy", "healthy"), res("2", "a-warning", "warning"), res("3", "c-critical", "critical"), res("4", "d-unknown", "unknown")];

const project: Project = makeProject({ name: "CRM", slug: "crm" });

function resourceHandlers() {
  return [
    http.get("*/api/v1/resources", ({ request }) => {
      const pageSize = Number(new URL(request.url).searchParams.get("page_size"));
      return HttpResponse.json({ items: pageSize === 1 ? [] : items, total: items.length, page: 1, page_size: pageSize });
    }),
    http.get("*/api/v1/resources/facets", () =>
      HttpResponse.json({ resource_types: [], locations: [], resource_groups: [], subscriptions: [], health: [] }),
    ),
    http.get("*/api/v1/projects", () => HttpResponse.json([project])),
  ];
}

describe("resource ordering", () => {
  it("sorts by health severity, then name", () => {
    expect(sortResources(items, "health").map((r) => r.name)).toEqual(["c-critical", "a-warning", "d-unknown", "b-healthy"]);
    expect(sortResources(items, "name").map((r) => r.name)[0]).toBe("a-warning");
  });
});

describe("Resources page", () => {
  it("lists attention first and bulk-assigns selected resources", async () => {
    const assigned: { id: string; body: unknown }[] = [];
    server.use(
      ...resourceHandlers(),
      http.put("*/api/v1/resources/:id/assignment", async ({ params, request }) => {
        assigned.push({ id: String(params.id), body: await request.json() });
        return HttpResponse.json(items.find((r) => r.id === params.id));
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ResourcesPage />);

    const names = await screen.findAllByRole("link", { name: /-(critical|warning|unknown|healthy)$/ });
    expect(names.map((n) => n.textContent)).toEqual(["c-critical", "a-warning", "d-unknown", "b-healthy"]);

    await user.click(screen.getByLabelText("Select c-critical"));
    await user.click(screen.getByLabelText("Select a-warning"));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    expect(bar).toHaveTextContent("2 selected");
    await user.click(within(bar).getByRole("button", { name: /Assign to project/ }));

    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Project"), "p1");
    await user.selectOptions(within(dialog).getByLabelText("Environment"), "e1");
    await user.click(within(dialog).getByRole("button", { name: "Assign" }));

    expect(await screen.findByText("2 resources assigned to CRM / Production")).toBeInTheDocument();
    expect(assigned.map((a) => a.id).sort()).toEqual(["2", "3"]);
    expect(assigned[0].body).toEqual({ project_id: "p1", environment_id: "e1" });
  });

  it("does not offer selection to viewers", async () => {
    server.use(...resourceHandlers(), http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)));
    renderWithProviders(<ResourcesPage />);
    expect(await screen.findByText("c-critical")).toBeInTheDocument();
    await vi.waitFor(() => expect(screen.queryByLabelText("Select c-critical")).not.toBeInTheDocument());
  });
});

describe("Overview", () => {
  it("greets the user, summarises environments and leads with what needs attention", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () => HttpResponse.json({ ...viewer, display_name: "Aditya Kumar" })),
      http.get("*/api/v1/projects", () => HttpResponse.json([])),
      http.get("*/api/v1/overview", () =>
        HttpResponse.json({
          is_mock: false,
          generated_at: "2026-10-06T10:00:00Z",
          last_synced_at: null,
          environment_health: { healthy: 9, warning: 2, critical: 1, unknown: 0 },
          totals: { projects: 1, environments: 1, subscriptions: 1, connections: 1, resources: 288, monitored_resources: 74, inventory_resources: 214, unassigned_resources: 3 },
          health: { healthy: 72, warning: 2, critical: 0, unknown: 0, total: 74 },
          needs_attention: [
            { id: "r9", name: "afd-crm-prod-uks", type_display_name: "Azure Front Door", project_name: "CRM", environment_name: "Production", health_status: "warning", reason: "5xx rate 1.75%, above 1%" },
          ],
          alerts: { active: 0, by_severity: {} },
          project_health: [],
          recent_alerts: [],
          resource_types: [],
          service_health: [],
          recent_changes: [],
          feed_errors: [],
        }),
      ),
    );
    renderWithProviders(<OverviewPage />);
    expect(await screen.findByRole("heading", { name: /, Aditya$/ })).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Status summary" });
    expect(within(summary).getByText("Warnings").parentElement?.parentElement).toHaveTextContent("2");
    expect(within(summary).getByText("Critical").parentElement?.parentElement).toHaveTextContent("1");
    expect(screen.getByText(/Azure data synchronised/)).toHaveTextContent("not yet");
    expect(screen.getByRole("link", { name: "afd-crm-prod-uks" })).toHaveAttribute("href", "/resources/r9");
    expect(screen.getByRole("link", { name: "Review unassigned resources" })).toBeInTheDocument();
    expect(await screen.findByText("No projects yet")).toBeInTheDocument();
    expect(screen.getByText("5xx rate 1.75%, above 1%")).toBeInTheDocument();
    expect(screen.getByText("No active alerts.")).toBeInTheDocument();
  });
});
