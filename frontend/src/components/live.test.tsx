import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { TopBar } from "@/layouts/TopBar";
import { ResourceDetailPage } from "@/pages/Resources/ResourceDetailPage";
import { resource } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { LiveMetric, LiveResourceState, LiveResources } from "@/types/api";
import { EnvironmentResourceTable } from "./EnvironmentResourceTable";
import { liveKeyMetric } from "./live";
import { ResourcesTable } from "./ResourcesTable";

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
    values: [38, 40, null, 41, 42],
    unavailable_reason: null,
    ...overrides,
  };
}

function liveState(overrides: Partial<LiveResourceState> = {}): LiveResourceState {
  return {
    id: "r1",
    status: "critical",
    reasons: [
      { signal: "metric", severity: "critical", message: "HTTP 5xx", metric: "http5xx", label: "HTTP 5xx", unit: "count", value: 64, operator: "gt", threshold: 50, window_minutes: 15 },
    ],
    evaluated_status: "healthy",
    evaluated_at: "2026-10-08T09:55:00+00:00",
    metrics: [liveMetric(), liveMetric({ key: "http5xx", label: "HTTP 5xx", unit: "count", latest: 7, window_value: 64, status: "critical", warning: 10, critical: 50 })],
    checked_at: "2026-10-08T10:00:05+00:00",
    ...overrides,
  };
}

function liveResponse(states: LiveResourceState[]): LiveResources {
  return {
    is_mock: true,
    generated_at: "2026-10-08T10:00:05+00:00",
    window_minutes: 60,
    interval_seconds: 60,
    resources: Object.fromEntries(states.map((s) => [s.id, s])),
  };
}

/** Serves live state and records which ids were asked for. */
function serveLive(states: LiveResourceState[]) {
  const requested: string[][] = [];
  server.use(
    http.get("*/api/v1/live/resources", ({ request }) => {
      requested.push((new URL(request.url).searchParams.get("ids") ?? "").split(","));
      return HttpResponse.json(liveResponse(states));
    }),
  );
  return requested;
}

describe("liveKeyMetric", () => {
  it("picks the worst metric with data", () => {
    expect(liveKeyMetric(liveState())?.key).toBe("http5xx");
    expect(liveKeyMetric(liveState({ metrics: [liveMetric({ latest: null, status: "critical" }), liveMetric({ key: "mem" })] }))?.key).toBe("mem");
    expect(liveKeyMetric(undefined)).toBeNull();
  });
});

describe("Live toggle", () => {
  it("switches the whole dashboard into Live mode with a fixed one-hour window", async () => {
    renderWithProviders(<TopBar onToggleSidebar={() => {}} onOpenMobileNav={() => {}} />);
    const toggle = screen.getByRole("button", { name: "Live" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Time range" })).toBeInTheDocument();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Time range" })).not.toBeInTheDocument();
    expect(screen.getByText(/Last 60 minutes · every 5 s/)).toBeInTheDocument();

    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Time range" })).toBeInTheDocument();
  });
});

describe("Resource tables in Live mode", () => {
  it("adds live status and live metrics for each row on the Resources page", async () => {
    const requested = serveLive([liveState()]);
    renderWithProviders(<ResourcesTable resources={[resource]} />, { live: true });

    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(requested[0]).toEqual(["r1"]);
    const row = screen.getByRole("row", { name: /app-crm-prod-uks/ });
    expect(within(row).getByText("Critical")).toBeInTheDocument();
    expect(within(row).getByRole("img", { name: /HTTP 5xx, last 5 minutes, latest 7/ })).toBeInTheDocument();
    expect(within(row).getByText("42%")).toBeInTheDocument();
  });

  it("orders rows by live status and lets the user restore health ordering", async () => {
    serveLive([liveState({ id: "r2", status: "critical" }), liveState({ id: "r1", status: "healthy", reasons: [] })]);
    const sorts: string[] = [];
    const stored = [
      { ...resource, id: "r1", name: "a-was-critical", health_status: "critical" as const },
      { ...resource, id: "r2", name: "b-was-healthy", health_status: "healthy" as const },
    ];
    renderWithProviders(<ResourcesTable resources={stored} sort="health" onSort={(s) => sorts.push(s)} />, { live: true });

    await waitFor(() => {
      const names = screen.getAllByRole("link").map((a) => a.textContent);
      expect(names).toEqual(["b-was-healthy", "a-was-critical"]);
    });
    await userEvent.click(screen.getByRole("button", { name: "Live status" }));
    expect(sorts).toEqual(["-health"]);
  });

  it("asks for nothing and shows the last evaluation when Live is off", async () => {
    const requested = serveLive([liveState()]);
    renderWithProviders(<ResourcesTable resources={[resource]} />);
    expect(await screen.findByRole("link", { name: "app-crm-prod-uks" })).toBeInTheDocument();
    expect(screen.queryByText("Live status")).not.toBeInTheDocument();
    expect(requested).toEqual([]);
  });

  it("replaces status, key metric and last-checked time in an environment", async () => {
    serveLive([liveState()]);
    server.use(
      http.get("*/api/v1/resources", () => HttpResponse.json({ items: [resource], total: 1, page: 1, page_size: 25 })),
      http.get("*/api/v1/resources/facets", () => HttpResponse.json({ health: [], resource_types: [], locations: [], resource_groups: [], subscriptions: [] })),
    );
    renderWithProviders(<EnvironmentResourceTable projectId="p1" environmentId="e1" />, { live: true });

    const row = (await screen.findAllByRole("row")).find((r) => r.textContent?.includes("app-crm-prod-uks"));
    await within(row as HTMLElement).findByText("Critical");
    expect(within(row as HTMLElement).getByText("HTTP 5xx")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("Live")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Updated" })).toBeInTheDocument();
  });
});

describe("Live failures", () => {
  it("says live data is unavailable instead of showing stale or endless loading values", async () => {
    server.use(http.get("*/api/v1/live/resources", () => HttpResponse.json({ error: { code: "AZURE_THROTTLED", message: "Busy" } }, { status: 503 })));
    renderWithProviders(
      <>
        <TopBar onToggleSidebar={() => {}} onOpenMobileNav={() => {}} />
        <ResourcesTable resources={[resource]} />
      </>,
      { live: true },
    );
    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Live/ })).toHaveAccessibleDescription("Live data unavailable, retrying");
  });

  it("marks readings as paused when a later poll fails", async () => {
    let fail = false;
    server.use(
      http.get("*/api/v1/live/resources", () =>
        fail ? HttpResponse.json({ error: { code: "NETWORK", message: "Down" } }, { status: 502 }) : HttpResponse.json(liveResponse([liveState()])),
      ),
      http.get("*/api/v1/resources", () => HttpResponse.json({ items: [resource], total: 1, page: 1, page_size: 25 })),
      http.get("*/api/v1/resources/facets", () => HttpResponse.json({ health: [], resource_types: [], locations: [], resource_groups: [], subscriptions: [] })),
    );
    const { client } = renderWithProviders(<EnvironmentResourceTable projectId="p1" environmentId="e1" />, { live: true });
    expect(await screen.findByText("Live")).toBeInTheDocument();

    fail = true;
    await client.refetchQueries({ queryKey: ["live-resources"] });
    expect(await screen.findByText("Live paused · retrying")).toBeInTheDocument();
    // The last readings stay visible, but are no longer presented as live.
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.getByText("HTTP 5xx")).toBeInTheDocument();
  });
});

describe("Resource page in Live mode", () => {
  it("shows the live status, live metric tiles and live health reasons", async () => {
    serveLive([liveState()]);
    server.use(
      http.get("*/api/v1/resources/r1", () => HttpResponse.json(resource)),
      http.get("*/api/v1/dashboards/by-resource/r1", () => HttpResponse.json({ error: { code: "NOT_FOUND", message: "No dashboard." } }, { status: 404 })),
    );
    renderWithProviders(
      <Routes>
        <Route path="/resources/:resourceId" element={<ResourceDetailPage />} />
      </Routes>,
      { route: "/resources/r1", live: true },
    );

    const tiles = await screen.findByRole("region", { name: "Live metrics" });
    expect(within(tiles).getByText("42%")).toBeInTheDocument();
    expect(within(tiles).getByText("critical")).toBeInTheDocument();
    // The stored evaluation said healthy; the header follows the live reading.
    const heading = screen.getByRole("heading", { name: "app-crm-prod-uks" }).parentElement as HTMLElement;
    expect(within(heading).getByTestId("health-badge")).toHaveTextContent("Critical");
    expect(within(heading).getByText("Live")).toBeInTheDocument();
  });
});
