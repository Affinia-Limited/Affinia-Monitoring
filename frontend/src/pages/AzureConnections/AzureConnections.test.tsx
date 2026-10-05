import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { me, viewer } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { Connection, SyncRun, SyncStep } from "@/types/api";
import { AddConnectionWizard, MOCK_SUBSCRIPTIONS, MOCK_TENANT } from "./AddConnectionWizard";
import { AzureConnectionsPage } from "./AzureConnectionsPage";

const LABELS = [
  ["authenticate", "Authenticate to Azure"],
  ["subscriptions", "Verify subscriptions"],
  ["permissions", "Verify read permissions"],
  ["discover", "Discover resources"],
  ["categorise", "Categorise and assign resources"],
  ["dashboards", "Apply dashboard templates"],
  ["health", "Evaluate health"],
] as const;

function run(status: SyncRun["status"], done: number): SyncRun {
  const steps: SyncStep[] = LABELS.map(([key, label], i) => ({
    key,
    label,
    status: i < done ? "succeeded" : i === done && status === "running" ? "running" : "pending",
    detail: key === "discover" && i < done ? "27 resources discovered" : null,
  }));
  return {
    id: "run1",
    connection_id: "c1",
    trigger: "initial",
    status,
    steps,
    stats: { discovered: 27 },
    started_at: "2026-09-30T10:00:00Z",
    finished_at: status === "succeeded" ? "2026-09-30T10:01:00Z" : null,
    error_code: null,
    error_message: null,
    created_at: "2026-09-30T10:00:00Z",
  };
}

const connection: Connection = {
  id: "c1",
  name: "Demo subscriptions",
  tenant_id: MOCK_TENANT,
  auth_method: "managed_identity",
  status: "pending",
  sync_enabled: true,
  last_sync_at: null,
  last_error_code: null,
  last_error_message: null,
  default_project_id: null,
  default_environment_id: null,
  created_at: "2026-09-30T10:00:00Z",
  subscriptions: [],
  resource_count: 0,
  latest_run: null,
};

describe("Add Azure subscription wizard", () => {
  it("creates a connection, shows progress and a success summary", async () => {
    let polls = 0;
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get("*/api/v1/azure/identity", () =>
        HttpResponse.json({
          provider: "mock",
          auth_methods: ["managed_identity", "workload_identity"],
          client_id: null,
          home_tenant_id: null,
          required_roles: [{ role: "Reader", scope: "Subscription", purpose: "Resource discovery" }],
          is_mock: true,
        }),
      ),
      http.post("*/api/v1/azure/connections", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ connection, sync_run: run("queued", 0) }, { status: 202 });
      }),
      http.get("*/api/v1/azure/sync-runs/run1", () => {
        polls += 1;
        return HttpResponse.json(polls < 2 ? run("running", 3) : run("succeeded", 7));
      }),
      http.get("*/api/v1/azure/connections", () => HttpResponse.json([])),
    );

    const user = userEvent.setup();
    renderWithProviders(<AddConnectionWizard open onOpenChange={() => {}} />);

    expect(await screen.findByText(/No passwords or client secrets are requested or stored/)).toBeInTheDocument();
    expect(screen.getByText("Reader")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));

    // Mock provider: tenant and demo subscriptions are prefilled.
    expect(screen.getByLabelText("Tenant ID")).toHaveValue(MOCK_TENANT);
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByText("Discover resources", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(await screen.findByText("Setup complete.", {}, { timeout: 6000 })).toBeInTheDocument();
    expect(screen.getByText("Connected successfully")).toBeInTheDocument();
    expect(screen.getByText("27")).toBeInTheDocument();
    expect(body).toMatchObject({ tenant_id: MOCK_TENANT, subscription_ids: MOCK_SUBSCRIPTIONS });
  }, 15_000);
});

describe("Azure Connections permissions", () => {
  it("hides the connect button from viewers", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)),
      http.get("*/api/v1/azure/connections", () => HttpResponse.json([])),
    );
    renderWithProviders(<AzureConnectionsPage />);
    expect(await screen.findByText("No Azure subscriptions connected")).toBeInTheDocument();
    expect(await screen.findByText(/Ask an administrator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add Azure subscription/ })).not.toBeInTheDocument();
  });

  it("shows the connect button to administrators", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () => HttpResponse.json(me())),
      http.get("*/api/v1/azure/connections", () => HttpResponse.json([])),
    );
    renderWithProviders(<AzureConnectionsPage />);
    expect(await screen.findByRole("button", { name: /Add Azure subscription/ })).toBeInTheDocument();
  });
});
