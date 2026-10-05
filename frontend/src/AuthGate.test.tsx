import { useQuery } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { endpoints } from "@/api/endpoints";
import { MeGate } from "@/AuthGate";
import { me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

const NOT_GRANTED = {
  error: {
    code: "ACCESS_NOT_GRANTED",
    message: "Your account has been authenticated but has not been granted access to this application.",
    request_id: "r1",
  },
};

function ProtectedApp() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: endpoints.projects, retry: false });
  return (
    <div>
      <h1>Dashboard</h1>
      <button type="button" onClick={() => void projects.refetch()}>
        Reload projects
      </button>
    </div>
  );
}

describe("Access gate", () => {
  it("shows a checking state and never renders the app before access is confirmed", async () => {
    server.use(
      http.get("*/api/v1/auth/me", async () => {
        await delay(50);
        return HttpResponse.json(me());
      }),
    );
    renderWithProviders(
      <MeGate>
        <ProtectedApp />
      </MeGate>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Checking access...");
    expect(screen.queryByRole("heading", { name: "Dashboard" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("shows the access-not-granted page without technical details", async () => {
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(NOT_GRANTED, { status: 403 })));
    renderWithProviders(
      <MeGate>
        <ProtectedApp />
      </MeGate>,
    );
    expect(await screen.findByRole("heading", { name: "Access not granted" })).toBeInTheDocument();
    expect(screen.getByText(/was authenticated successfully, but you have not been granted access/)).toBeInTheDocument();
    expect(screen.queryByText(/Request ID/)).not.toBeInTheDocument();
    expect(screen.queryByText("ACCESS_NOT_GRANTED")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Dashboard" })).not.toBeInTheDocument();
  });

  it("shows the suspension message for suspended users", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ error: { code: "ACCESS_SUSPENDED", message: "Suspended." } }, { status: 403 }),
      ),
    );
    renderWithProviders(
      <MeGate>
        <ProtectedApp />
      </MeGate>,
    );
    expect(await screen.findByRole("heading", { name: "Access suspended" })).toBeInTheDocument();
    expect(screen.getByText(/has been temporarily suspended/)).toBeInTheDocument();
  });

  it("Try again re-checks access", async () => {
    let granted = false;
    server.use(
      http.get("*/api/v1/auth/me", () => (granted ? HttpResponse.json(me()) : HttpResponse.json(NOT_GRANTED, { status: 403 }))),
    );
    renderWithProviders(
      <MeGate>
        <ProtectedApp />
      </MeGate>,
    );
    await screen.findByRole("heading", { name: "Access not granted" });
    granted = true;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("replaces the app and drops cached data when access is revoked mid-session", async () => {
    let suspended = false;
    server.use(
      http.get("*/api/v1/projects", () =>
        suspended
          ? HttpResponse.json({ error: { code: "ACCESS_SUSPENDED", message: "Suspended." } }, { status: 403 })
          : HttpResponse.json([]),
      ),
    );
    const { client } = renderWithProviders(
      <MeGate>
        <ProtectedApp />
      </MeGate>,
    );
    await screen.findByRole("heading", { name: "Dashboard" });
    await waitFor(() => expect(client.getQueryData(["projects"])).toEqual([]));
    suspended = true;
    await userEvent.click(screen.getByRole("button", { name: "Reload projects" }));
    expect(await screen.findByRole("heading", { name: "Access suspended" })).toBeInTheDocument();
    expect(client.getQueryData(["projects"])).toBeUndefined();
  });
});
