import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { environment, project, resource, viewer } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { AlertPlan, AlertTemplate, AlertTemplateAssignment, TemplateRule } from "@/types/api";
import { SettingsPage } from "@/pages/Settings/SettingsPage";
import { AlertsPage } from "./AlertsPage";
import { AlertTemplates } from "./AlertTemplates";
import { coverageFor, EnvironmentAlertCoverage, RecommendedAlertsPanel } from "./CoveragePanels";
import { tierOrderError } from "./templateShared";

function rule(overrides: Partial<TemplateRule> = {}): TemplateRule {
  return {
    metric: "plan_cpu",
    label: "Plan CPU",
    unit: "percent",
    description: "",
    operator: "gt",
    reducer: "avg",
    window_minutes: 15,
    frequency_minutes: 5,
    info: 70,
    warning: 80,
    critical: 90,
    default_info: 70,
    default_warning: 80,
    default_critical: 90,
    default_window_minutes: 15,
    enabled: true,
    customized: false,
    ...overrides,
  };
}

function template(overrides: Partial<AlertTemplate> = {}): AlertTemplate {
  return {
    monitor_key: "app_service",
    display_name: "App Service",
    category: "Compute",
    description: "Web apps",
    customized: false,
    resource_count: 4,
    covered_count: 2,
    rules: [rule(), rule({ metric: "health_check", label: "Health check", operator: "lt", info: null, warning: 95, critical: 80, default_info: null, default_warning: 95, default_critical: 80 })],
    ...overrides,
  };
}

function assignment(overrides: Partial<AlertTemplateAssignment> = {}): AlertTemplateAssignment {
  return {
    id: "as1",
    scope: "environment",
    resource_id: null,
    project_id: "p1",
    environment_id: "e1",
    resource_name: null,
    project_name: "Project One",
    environment_name: "Production",
    enabled: true,
    overrides: {},
    notification_channel_ids: [],
    covered_resources: 7,
    templates: ["app_service"],
    created_at: "2026-10-12T10:00:00Z",
    updated_at: "2026-10-12T10:00:00Z",
    ...overrides,
  };
}

interface Calls {
  posts: Record<string, unknown>[];
  patches: { id: string; body: Record<string, unknown> }[];
  deletes: string[];
  puts: Record<string, unknown>[];
  resets: string[];
}

function serve({
  templates = [template()],
  assignments = [] as AlertTemplateAssignment[],
  conflict = false,
  putError = false,
}: { templates?: AlertTemplate[]; assignments?: AlertTemplateAssignment[]; conflict?: boolean; putError?: boolean } = {}): Calls {
  const calls: Calls = { posts: [], patches: [], deletes: [], puts: [], resets: [] };
  server.use(
    http.get("*/api/v1/alert-templates", () => HttpResponse.json(templates)),
    http.get("*/api/v1/alert-templates/:key", ({ params }) => HttpResponse.json(templates.find((t) => t.monitor_key === params.key))),
    http.put("*/api/v1/alert-templates/:key/rules/:metric", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.puts.push(body);
      if (putError) {
        return HttpResponse.json({ error: { code: "VALIDATION_FAILED", message: "Critical must be higher than Warning for this metric." } }, { status: 422 });
      }
      return HttpResponse.json(rule({ ...(body as Partial<TemplateRule>), customized: true }));
    }),
    http.delete("*/api/v1/alert-templates/:key/rules/:metric", ({ params }) => {
      calls.resets.push(String(params.metric));
      return HttpResponse.json(rule());
    }),
    http.get("*/api/v1/alert-template-assignments", () => HttpResponse.json(assignments)),
    http.post("*/api/v1/alert-template-assignments", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.posts.push(body);
      if (conflict) {
        return HttpResponse.json({ error: { code: "ASSIGNMENT_EXISTS", message: "Already covered.", details: { id: "as1" } } }, { status: 409 });
      }
      return HttpResponse.json(assignment({ id: "new", ...(body as Partial<AlertTemplateAssignment>) }), { status: 201 });
    }),
    http.patch("*/api/v1/alert-template-assignments/:id", async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.patches.push({ id: String(params.id), body });
      return HttpResponse.json(assignment({ ...(body as Partial<AlertTemplateAssignment>) }));
    }),
    http.delete("*/api/v1/alert-template-assignments/:id", ({ params }) => {
      calls.deletes.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
    http.get("*/api/v1/projects", () => HttpResponse.json([project()])),
    http.get("*/api/v1/notification-channels", () => HttpResponse.json([])),
    http.get("*/api/v1/resources", () => HttpResponse.json({ items: [resource], total: 1, page: 1, page_size: 8 })),
  );
  return calls;
}

describe("tier order", () => {
  it("matches the direction of the condition", () => {
    expect(tierOrderError("gt", { info: 70, warning: 80, critical: 90 })).toBeNull();
    expect(tierOrderError("gt", { info: null, warning: 80, critical: 75 })).toMatch(/Critical must be higher than Warning/);
    expect(tierOrderError("lt", { info: null, warning: 95, critical: 80 })).toBeNull();
    expect(tierOrderError("lt", { info: null, warning: 80, critical: 95 })).toMatch(/Critical must be lower than Warning/);
    expect(tierOrderError("gt", { info: null, warning: null, critical: null })).toMatch(/at least one threshold/);
  });
});

describe("Alert templates: template rules", () => {
  it("lists each type's rules with Info, Warning and Critical levels", async () => {
    serve();
    renderWithProviders(<AlertTemplates />);
    const section = await screen.findByRole("region", { name: "App Service" });
    expect(within(section).getByText("4 resources, 2 covered", { exact: false })).toBeInTheDocument();
    const row = within(section).getByRole("row", { name: /Plan CPU/ });
    expect(within(row).getByText("70%")).toBeInTheDocument();
    expect(within(row).getByText("80%")).toBeInTheDocument();
    expect(within(row).getByText("90%")).toBeInTheDocument();
    expect(within(row).getByText("above")).toBeInTheDocument();
  });

  it("validates tier order before saving, shows server errors, and resets to recommended", async () => {
    const calls = serve({ templates: [template({ rules: [rule({ customized: true, critical: 95 })] })], putError: true });
    renderWithProviders(<AlertTemplates />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit App Service Plan CPU" }));
    const dialog = await screen.findByRole("dialog");
    const critical = within(dialog).getByLabelText("Critical");
    await userEvent.clear(critical);
    await userEvent.type(critical, "75");
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Critical must be higher than Warning");
    expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(within(dialog).getByText("Recommended: 90%")).toBeInTheDocument();

    await userEvent.clear(critical);
    await userEvent.type(critical, "92");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Critical must be higher than Warning for this metric.")).toBeInTheDocument();
    expect(calls.puts[0]).toEqual({ enabled: true, info: 70, warning: 80, critical: 92, window_minutes: 15 });

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset App Service Plan CPU to recommended" }));
    await waitFor(() => expect(calls.resets).toEqual(["plan_cpu"]));
  });
});

describe("Alert templates: coverage", () => {
  it("applies the template to one resource with a changed threshold", async () => {
    const calls = serve();
    renderWithProviders(<AlertTemplates />);
    await userEvent.click((await screen.findAllByRole("button", { name: /Apply recommended alerts/ }))[0]);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /app-crm-prod-uks/ }));
    const warning = await within(dialog).findByLabelText("Plan CPU Warning threshold (percent)");
    await userEvent.clear(warning);
    await userEvent.type(warning, "85");
    await userEvent.click(within(dialog).getByLabelText("Health check alert on"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply recommended alerts" }));

    await screen.findByText("Recommended alerts applied");
    expect(calls.posts).toEqual([
      {
        notification_channel_ids: [],
        resource_id: "r1",
        overrides: { "app_service:plan_cpu": { warning: 85 }, "app_service:health_check": { enabled: false } },
      },
    ]);
  });

  it("blocks an inline change that breaks the tier order", async () => {
    serve();
    renderWithProviders(<AlertTemplates />);
    await userEvent.click((await screen.findAllByRole("button", { name: /Apply recommended alerts/ }))[0]);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /app-crm-prod-uks/ }));
    const critical = await within(dialog).findByLabelText("Plan CPU Critical threshold (percent)");
    await userEvent.clear(critical);
    await userEvent.type(critical, "50");
    expect(within(dialog).getByRole("button", { name: "Apply recommended alerts" })).toBeDisabled();
  });

  it("covers a whole environment and lists the resource types", async () => {
    const calls = serve();
    renderWithProviders(<AlertTemplates />);
    await userEvent.click((await screen.findAllByRole("button", { name: /Apply recommended alerts/ }))[0]);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("radio", { name: "Environment" }));
    await userEvent.selectOptions(within(dialog).getByLabelText("Project"), "p1");
    await userEvent.selectOptions(within(dialog).getByLabelText("Environment"), "e1");
    expect(within(dialog).getByText("2 alerts · 4 resources")).toBeInTheDocument();
    expect(within(dialog).getByText(/most specific one wins/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply recommended alerts" }));
    await screen.findByText("Recommended alerts applied");
    expect(calls.posts).toEqual([{ notification_channel_ids: [], project_id: "p1", environment_id: "e1" }]);
  });

  it("offers to edit the existing coverage instead of duplicating it", async () => {
    serve({ conflict: true, assignments: [assignment({ scope: "organization", project_id: null, environment_id: null, project_name: null, environment_name: null })] });
    renderWithProviders(<AlertTemplates />);
    await screen.findByText("All projects");
    await userEvent.click(screen.getAllByRole("button", { name: /Apply recommended alerts/ })[0]);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("radio", { name: "Everything" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply recommended alerts" }));
    await userEvent.click(await within(dialog).findByRole("button", { name: "Edit the existing coverage" }));
    expect(await screen.findByRole("dialog", { name: "Customise: All projects" })).toBeInTheDocument();
  });

  it("turns coverage off and removes it", async () => {
    const calls = serve({ assignments: [assignment({ overrides: { "app_service:plan_cpu": { warning: 85 } } })] });
    renderWithProviders(<AlertTemplates />);
    expect(await screen.findByText("Project One / Production")).toBeInTheDocument();
    expect(screen.getByText("1 customised")).toBeInTheDocument();
    expect(screen.getByText("7 resources covered · App Service")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: "Turn off recommended alerts for Project One / Production" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove coverage" }));
    expect(calls.patches).toEqual([{ id: "as1", body: { enabled: false } }]);
    expect(calls.deletes).toEqual(["as1"]);
  });
});

describe("Alert templates: permissions and navigation", () => {
  it("is read-only for viewers", async () => {
    serve({ assignments: [assignment()] });
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)));
    renderWithProviders(<AlertsPage />, { route: "/alerts?tab=templates" });
    await screen.findByRole("region", { name: "App Service" });
    expect(screen.getByRole("tab", { name: "Alert templates" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Custom rules" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply recommended alerts/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Edit App Service/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeDisabled();
  });

  it("points Settings to the alert templates", async () => {
    renderWithProviders(<SettingsPage />, { route: "/settings?tab=thresholds" });
    expect(await screen.findByRole("link", { name: "Open alert templates" })).toHaveAttribute("href", "/alerts?tab=templates");
  });
});

describe("Recommended alerts on a resource", () => {
  function plan(overrides: Partial<AlertPlan> = {}): AlertPlan {
    return {
      resource_id: "r1",
      monitor_key: "app_service",
      template: template(),
      assignment: assignment(),
      rules: [{ ...rule(), current_value: 84, current_tier: "warning", overridden: false }],
      ...overrides,
    };
  }

  it("shows the coverage, effective thresholds and current level", async () => {
    serve();
    server.use(http.get("*/api/v1/resources/r1/alert-plan", () => HttpResponse.json(plan())));
    renderWithProviders(<RecommendedAlertsPanel resource={resource} />);
    expect(await screen.findByText("Project One / Production")).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Plan CPU/ });
    expect(within(row).getByText("84%")).toBeInTheDocument();
    expect(within(row).getByText("Warning")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Customise for this resource/ })).toBeInTheDocument();
  });

  it("turns recommended alerts off for one resource", async () => {
    const calls = serve();
    server.use(http.get("*/api/v1/resources/r1/alert-plan", () => HttpResponse.json(plan())));
    renderWithProviders(<RecommendedAlertsPanel resource={resource} />);
    await userEvent.click(await screen.findByRole("button", { name: /Turn off for this resource/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Turn off" }));
    await screen.findByText("Recommended alerts off");
    expect(calls.posts).toEqual([{ resource_id: "r1", enabled: false }]);
  });

  it("enables recommended alerts when the resource is not covered", async () => {
    const calls = serve();
    server.use(http.get("*/api/v1/resources/r1/alert-plan", () => HttpResponse.json(plan({ assignment: null }))));
    renderWithProviders(<RecommendedAlertsPanel resource={resource} />);
    expect(await screen.findByText("Not covered")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Enable recommended alerts/ }));
    await screen.findByText("Recommended alerts on");
    expect(calls.posts).toEqual([{ resource_id: "r1" }]);
  });

  it("explains when a resource type has no template", async () => {
    serve();
    server.use(http.get("*/api/v1/resources/r1/alert-plan", () => HttpResponse.json(plan({ template: null, assignment: null, rules: [], monitor_key: null }))));
    renderWithProviders(<RecommendedAlertsPanel resource={resource} />);
    expect(await screen.findByText(/no alert template for this resource type/)).toBeInTheDocument();
  });
});

describe("Alert coverage of an environment", () => {
  it("picks the most specific coverage", () => {
    const org = assignment({ id: "o", scope: "organization", project_id: null, environment_id: null });
    const prj = assignment({ id: "p", scope: "project", environment_id: null });
    const env = assignment({ id: "e" });
    expect(coverageFor([org, prj, env], "p1", "e1")?.id).toBe("e");
    expect(coverageFor([org, prj], "p1", "e1")?.id).toBe("p");
    expect(coverageFor([org], "p1", "e1")?.id).toBe("o");
    expect(coverageFor([], "p1", "e1")).toBeNull();
  });

  it("applies recommended alerts to an uncovered environment", async () => {
    const calls = serve();
    renderWithProviders(<EnvironmentAlertCoverage projectId="p1" environmentId={environment().id} environmentName="Production" />);
    await userEvent.click(await screen.findByRole("button", { name: /Apply recommended alerts to this environment/ }));
    await screen.findByText("Recommended alerts applied");
    expect(calls.posts).toEqual([{ project_id: "p1", environment_id: "e1" }]);
  });
});
