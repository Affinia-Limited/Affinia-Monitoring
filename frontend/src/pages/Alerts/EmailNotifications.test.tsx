import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { project, viewer } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { EmailList } from "@/types/api";
import { AlertsPage } from "./AlertsPage";
import { EmailNotifications, parseRecipients } from "./EmailNotifications";

function emailList(overrides: Partial<EmailList> = {}): EmailList {
  return {
    id: "l1",
    name: "Platform on-call",
    enabled: true,
    recipients: ["ops@contoso.com", "lead@contoso.com"],
    min_severity: "critical",
    notify_resolved: true,
    project_id: null,
    environment_id: null,
    project_name: null,
    environment_name: null,
    created_at: "2026-10-08T10:00:00Z",
    updated_at: "2026-10-08T10:00:00Z",
    ...overrides,
  };
}

function serve(lists: EmailList[], status = { provider: "acs", configured: true }) {
  const posted: unknown[] = [];
  server.use(
    http.get("*/api/v1/notifications/email-status", () => HttpResponse.json(status)),
    http.get("*/api/v1/notifications/email-lists", () => HttpResponse.json(lists)),
    http.get("*/api/v1/projects", () => HttpResponse.json([project()])),
    http.post("*/api/v1/notifications/email-lists", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      posted.push(body);
      return HttpResponse.json(emailList({ id: "l2", ...(body as Partial<EmailList>) }), { status: 201 });
    }),
    http.post("*/api/v1/notifications/email-lists/:id/test", () =>
      HttpResponse.json({ status: "sent", message: "Test email sent to 2 recipient(s)." }),
    ),
  );
  return posted;
}

describe("parseRecipients", () => {
  it("splits, lower-cases, de-duplicates and reports invalid entries", () => {
    expect(parseRecipients("Ops@Contoso.com, lead@contoso.com\nops@contoso.com; nope  a@b")).toEqual({
      valid: ["ops@contoso.com", "lead@contoso.com"],
      invalid: ["nope", "a@b"],
    });
  });
});

describe("Email notifications", () => {
  it("lists recipients, severity and scope", async () => {
    serve([emailList(), emailList({ id: "l3", name: "CRM team", min_severity: "warning", project_id: "p1", project_name: "CRM", notify_resolved: false, enabled: false })]);
    renderWithProviders(<EmailNotifications />);

    expect(await screen.findByText("Platform on-call")).toBeInTheDocument();
    const lists = screen.getAllByRole("list", { name: "Recipients" });
    expect(within(lists[0]).getByText("ops@contoso.com")).toBeInTheDocument();
    expect(screen.getByText("Critical only")).toBeInTheDocument();
    expect(screen.getByText("Critical and warning")).toBeInTheDocument();
    expect(screen.getByText(/CRM, all environments/)).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.queryByText(/Email delivery is not set up/)).not.toBeInTheDocument();
  });

  it("warns when the deployment cannot send email", async () => {
    serve([], { provider: "none", configured: false });
    renderWithProviders(<EmailNotifications />);
    expect(await screen.findByText("Email delivery is not set up in this deployment")).toBeInTheDocument();
    expect(screen.getByText("No email lists yet")).toBeInTheDocument();
  });

  it("creates a list after validating the recipients", async () => {
    const posted = serve([]);
    const user = userEvent.setup();
    renderWithProviders(<EmailNotifications />);
    await user.click((await screen.findAllByRole("button", { name: /New email list/ }))[0]);

    await user.type(screen.getByLabelText("Name"), "Platform on-call");
    const recipients = screen.getByLabelText("Recipients");
    await user.type(recipients, "ops@contoso.com, not-an-email");
    expect(screen.getByRole("alert")).toHaveTextContent("Not valid email address: not-an-email");
    expect(screen.getByRole("button", { name: "Create list" })).toBeDisabled();

    await user.clear(recipients);
    await user.type(recipients, "Ops@Contoso.com{enter}lead@contoso.com");
    await user.selectOptions(screen.getByLabelText("Email when"), "warning");
    await user.selectOptions(screen.getByLabelText("Project"), "p1");
    await user.click(screen.getByRole("button", { name: "Create list" }));

    expect(await screen.findByText("Email list created")).toBeInTheDocument();
    expect(posted).toEqual([
      {
        name: "Platform on-call",
        recipients: ["ops@contoso.com", "lead@contoso.com"],
        min_severity: "warning",
        notify_resolved: true,
        enabled: true,
        project_id: "p1",
        environment_id: null,
      },
    ]);
  });

  it("sends a test email and reports the result", async () => {
    serve([emailList()]);
    const user = userEvent.setup();
    renderWithProviders(<EmailNotifications />);
    await user.click(await screen.findByRole("button", { name: /Send test email/ }));
    expect(await screen.findByText("Test email sent")).toBeInTheDocument();
    expect(screen.getByText("Test email sent to 2 recipient(s).")).toBeInTheDocument();
  });

  it("is only offered to people who manage alerts", async () => {
    serve([]);
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)));
    renderWithProviders(<AlertsPage />, { route: "/alerts?tab=email" });
    expect(await screen.findByRole("tab", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Email notifications" })).not.toBeInTheDocument();
  });
});
