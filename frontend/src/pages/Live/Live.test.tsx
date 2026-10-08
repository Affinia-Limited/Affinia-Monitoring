import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { alert, counts } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { Live, LiveEnvironment, LiveMetric, LiveResource } from "@/types/api";
import { diffLive } from "./liveChanges";
import { LivePage } from "./LivePage";

function liveMetric(overrides: Partial<LiveMetric> = {}): LiveMetric {
  return {
    key: "plan_cpu",
    label: "Plan CPU",
    unit: "percent",
    latest: 42,
    latest_at: "2026-10-08T10:00:00+00:00",
    window_value: 40,
    window_minutes: 15,
    reducer: "avg",
    operator: "gt",
    warning: 80,
    critical: 90,
    status: "healthy",
    points: [38, 40, null, 41, 42].map((value, i) => ({ timestamp: `2026-10-08T09:5${5 + i}:00+00:00`, value })),
    unavailable_reason: null,
    ...overrides,
  };
}

function liveEnv(overrides: Partial<LiveEnvironment> = {}): LiveEnvironment {
  return {
    project_id: "p1",
    project_name: "CRM",
    environment_id: "e1",
    environment_name: "Production",
    kind: "production",
    status: "healthy",
    counts: counts({ total: 3, healthy: 3 }),
    active_alerts: 0,
    last_checked_at: null,
    ...overrides,
  };
}

function liveResource(overrides: Partial<LiveResource> = {}): LiveResource {
  return {
    id: "r1",
    name: "app-crm-prod-uks",
    type_display_name: "App Service",
    project_id: "p1",
    project_name: "CRM",
    environment_id: "e1",
    environment_name: "Production",
    health_status: "healthy",
    health_evaluated_at: null,
    active_alerts: 0,
    metrics: [liveMetric()],
    ...overrides,
  };
}

function live(overrides: Partial<Live> = {}): Live {
  return {
    is_mock: true,
    generated_at: "2026-10-08T10:00:05+00:00",
    window_minutes: 60,
    interval_seconds: 60,
    health: counts({ total: 3, healthy: 3 }),
    alerts: { active: 0, by_severity: {} },
    environments: [liveEnv()],
    resources: [liveResource()],
    resources_total: 1,
    recent_alerts: [],
    ...overrides,
  };
}

describe("diffLive", () => {
  it("reports status transitions and newly opened alerts", () => {
    const before = live({ recent_alerts: [alert({ id: "old" })] });
    const after = live({
      generated_at: "2026-10-08T10:00:20+00:00",
      environments: [liveEnv({ status: "critical" })],
      resources: [liveResource({ health_status: "warning" })],
      recent_alerts: [alert({ id: "new", title: "HTTP 5xx > 50" }), alert({ id: "old" })],
    });
    const changes = diffLive(before, after);
    expect(changes.map((c) => [c.kind, c.detail.split(" · ")[0]])).toEqual([
      ["environment", "Environment worsened to critical"],
      ["resource", "App Service worsened to warning"],
      ["alert", "app-crm-prod-uks"],
    ]);
    expect(changes[0].href).toBe("/projects/p1/environments/e1");
  });

  it("describes recoveries and ignores resources that only entered the list", () => {
    const before = live({ resources: [liveResource({ health_status: "critical" })] });
    const after = live({
      generated_at: "2026-10-08T10:00:20+00:00",
      resources: [liveResource({ health_status: "healthy" }), liveResource({ id: "r2", health_status: "critical" })],
    });
    expect(diffLive(before, after).map((c) => c.detail)).toEqual(["App Service recovered from critical"]);
  });

  it("does not treat an older alert sliding into a full list as new", () => {
    const now = Date.parse("2026-10-08T10:00:00Z");
    const at = (minutes: number) => new Date(now - minutes * 60_000).toISOString();
    const full = Array.from({ length: 8 }, (_, i) => alert({ id: `a${i}`, started_at: at(i + 1) }));
    const before = live({ recent_alerts: full });
    const after = live({
      generated_at: "2026-10-08T10:00:20+00:00",
      recent_alerts: [...full.slice(1), alert({ id: "older", started_at: at(30) })],
    });
    expect(diffLive(before, after)).toEqual([]);
  });
});

describe("LivePage", () => {
  it("shows live status, environments and metrics for the selected scope", async () => {
    let params: URLSearchParams | null = null;
    server.use(
      http.get("*/api/v1/live", ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json(
          live({
            health: counts({ total: 4, healthy: 2, warning: 1, critical: 1 }),
            alerts: { active: 1, by_severity: { critical: 1 } },
            environments: [liveEnv({ status: "critical", counts: counts({ total: 4, healthy: 2, warning: 1, critical: 1 }), active_alerts: 1 })],
            resources: [liveResource({ health_status: "critical", metrics: [liveMetric({ latest: 94, status: "critical" })] })],
            resources_total: 4,
            recent_alerts: [alert()],
          }),
        );
      }),
    );
    renderWithProviders(<LivePage />, { route: "/live?project=p1" });

    expect(await screen.findByText("94%")).toBeInTheDocument();
    expect(params!.get("project_id")).toBe("p1");
    expect(screen.getByText("Live", { selector: "span" })).toBeInTheDocument();

    const summary = screen.getByRole("region", { name: "Live status summary" });
    expect(within(summary).getByText("Critical").parentElement?.parentElement).toHaveTextContent("1");
    expect(screen.getByRole("link", { name: /Production/ })).toHaveAttribute("href", "/projects/p1/environments/e1");
    expect(screen.getByText("2 of 4 resources need attention")).toBeInTheDocument();
    expect(screen.getByText(/Worst 1 of 4 monitored resources/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Plan CPU, last 5 minutes, latest 94%/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plan CPU > 90 on app-crm-prod-uks" })).toBeInTheDocument();
  });

  it("can be paused and resumed", async () => {
    server.use(http.get("*/api/v1/live", () => HttpResponse.json(live())));
    renderWithProviders(<LivePage />, { route: "/live" });
    await screen.findByText("42%");
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByText("Paused")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(screen.getByText("Live", { selector: "span" })).toBeInTheDocument();
  });

  it("keeps showing the last data when a refresh fails", async () => {
    let fail = false;
    server.use(
      http.get("*/api/v1/live", () => (fail ? HttpResponse.json({ error: { code: "AZURE_ERROR", message: "Down" } }, { status: 502 }) : HttpResponse.json(live()))),
    );
    renderWithProviders(<LivePage />, { route: "/live" });
    await screen.findByText("42%");
    fail = true;
    await userEvent.click(screen.getByRole("button", { name: "Refresh now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The last update failed");
    expect(screen.getByText("42%")).toBeInTheDocument();
  });
});
