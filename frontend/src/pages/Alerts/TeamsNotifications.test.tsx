import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { project, viewer } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { TeamsChannel } from "@/types/api";
import { AlertsPage } from "./AlertsPage";
import { secretEnvName, TeamsNotifications } from "./TeamsNotifications";

function teamsChannel(overrides: Partial<TeamsChannel> = {}): TeamsChannel {
  return {
    id: "t1",
    name: "Platform alerts",
    enabled: true,
    secret_ref: "org-1-teams-alerts",
    min_severity: "critical",
    notify_resolved: true,
    project_id: null,
    environment_id: null,
    project_name: null,
    environment_name: null,
    created_at: "2026-10-09T10:00:00Z",
    updated_at: "2026-10-09T10:00:00Z",
    ...overrides,
  };
}

function serve(channels: TeamsChannel[], testResult = { status: "sent", message: "Test notification sent." }) {
  const posted: Record<string, unknown>[] = [];
  const tested: string[] = [];
  server.use(
    http.get("*/api/v1/notifications/teams-setup", () => HttpResponse.json({ secret_prefix: "org-1-", secret_source: "environment" })),
    http.get("*/api/v1/notifications/teams-channels", () => HttpResponse.json(channels)),
    http.get("*/api/v1/projects", () => HttpResponse.json([project()])),
    http.post("*/api/v1/notifications/teams-channels", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      posted.push(body);
      return HttpResponse.json(teamsChannel({ id: "t2", ...(body as Partial<TeamsChannel>) }), { status: 201 });
    }),
    http.post("*/api/v1/notification-channels/:id/test", ({ params }) => {
      tested.push(String(params.id));
      return HttpResponse.json(testResult);
    }),
  );
  return { posted, tested };
}

describe("Microsoft Teams alerts", () => {
  it("names the local variable that holds a secret", () => {
    expect(secretEnvName("org-1-teams-alerts")).toBe("SECRET_ORG_1_TEAMS_ALERTS");
  });

  it("explains the setup for this deployment", async () => {
    serve([]);
    renderWithProviders(<TeamsNotifications />);
    await screen.findByText("No Teams channels yet");
    await userEvent.click(screen.getByRole("button", { name: /How to connect a Teams channel/ }));
    expect(screen.getByText(/Send webhook alerts to a channel/)).toBeInTheDocument();
    expect(screen.getByText('SECRET_ORG_1_TEAMS_ALERTS="<the URL>"')).toBeInTheDocument();
  });

  it("adds a channel with its secret name, never a URL", async () => {
    const { posted } = serve([]);
    renderWithProviders(<TeamsNotifications />);
    await userEvent.click((await screen.findAllByRole("button", { name: /New Teams channel/ }))[0]);
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Ops");
    const secret = within(dialog).getByLabelText("Webhook secret name");
    expect(secret).toHaveValue("org-1-teams-alerts");

    await userEvent.clear(secret);
    await userEvent.type(secret, "https://prod.example/workflows");
    expect(within(dialog).getByText("Enter the secret's name, not the webhook URL itself.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Add channel" })).toBeDisabled();

    await userEvent.clear(secret);
    await userEvent.type(secret, "contoso-teams");
    expect(within(dialog).getByText("The name must start with org-1-")).toBeInTheDocument();

    await userEvent.clear(secret);
    await userEvent.type(secret, "org-1-teams-ops");
    expect(within(dialog).getByText(/SECRET_ORG_1_TEAMS_OPS/)).toBeInTheDocument();
    await userEvent.selectOptions(within(dialog).getByLabelText("Post when"), "warning");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add channel" }));

    expect(posted).toEqual([
      {
        name: "Ops",
        secret_ref: "org-1-teams-ops",
        min_severity: "warning",
        notify_resolved: true,
        enabled: true,
        project_id: null,
        environment_id: null,
      },
    ]);
  });

  it("sends a test message and reports a failure clearly", async () => {
    const { tested } = serve([teamsChannel()], { status: "failed", message: "The channel's secret was not found." });
    renderWithProviders(<TeamsNotifications />);
    await userEvent.click(await screen.findByRole("button", { name: /Send test message/ }));
    expect(await screen.findByText("Test message not posted")).toBeInTheDocument();
    expect(screen.getByText("The channel's secret was not found.")).toBeInTheDocument();
    expect(tested).toEqual(["t1"]);
  });

  it("is a tab on the Alerts page for alert managers only", async () => {
    serve([teamsChannel()]);
    renderWithProviders(<AlertsPage />, { route: "/alerts?tab=teams" });
    expect(await screen.findByText("Platform alerts")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Microsoft Teams" })).toHaveAttribute("aria-selected", "true");
  });

  it("is hidden from viewers", async () => {
    serve([]);
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)));
    renderWithProviders(<AlertsPage />);
    expect(await screen.findByRole("tab", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Microsoft Teams" })).not.toBeInTheDocument();
  });
});
