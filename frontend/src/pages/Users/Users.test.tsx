import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { me, viewer } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { UserDetail, UserOut } from "@/types/api";
import { UserDetailPage } from "./UserDetailPage";
import { UsersPage } from "./UsersPage";

function user(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: "u2",
    email: "john@example.test",
    display_name: "John",
    first_name: null,
    last_name: null,
    role_key: "viewer",
    role_managed_by_entra: false,
    status: "active",
    last_login_at: "2026-10-01T10:00:00Z",
    invited_at: "2026-09-30T10:00:00Z",
    invitation_expires_at: null,
    activated_at: "2026-09-30T11:00:00Z",
    deactivated_at: null,
    created_at: "2026-09-30T10:00:00Z",
    created_by_name: "Test Admin",
    ...overrides,
  };
}

const self = user({ id: "u1", display_name: "Test Admin", email: "admin@example.test", role_key: "super_admin", created_by_name: null });
const john = user();
const sarah = user({ id: "u3", display_name: "Sarah", email: "sarah@example.test", role_key: "operator", status: "suspended" });

function listHandler(items: UserOut[], seen?: URLSearchParams[]) {
  return http.get("*/api/v1/users", ({ request }) => {
    seen?.push(new URL(request.url).searchParams);
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 25 });
  });
}

describe("Users page", () => {
  it("lists users with their role, status and who added them", async () => {
    server.use(listHandler([self, john, sarah]));
    renderWithProviders(<UsersPage />);
    const row = (await screen.findByRole("link", { name: "John" })).closest("tr") as HTMLElement;
    expect(within(row).getByText("john@example.test")).toBeInTheDocument();
    expect(within(row).getByText("Viewer")).toBeInTheDocument();
    expect(within(row).getByText("Active")).toBeInTheDocument();
    expect(within(row).getByText("Test Admin")).toBeInTheDocument();
    const sarahRow = screen.getByRole("link", { name: "Sarah" }).closest("tr") as HTMLElement;
    expect(within(sarahRow).getByText("Suspended")).toBeInTheDocument();
    // No actions on your own account.
    const selfRow = screen.getByRole("link", { name: "Test Admin" }).closest("tr") as HTMLElement;
    expect(within(selfRow).getByText("You")).toBeInTheDocument();
    expect(within(selfRow).queryByRole("button", { name: /Actions for/ })).not.toBeInTheDocument();
  });

  it("sends search and filters to the API", async () => {
    const seen: URLSearchParams[] = [];
    server.use(listHandler([john], seen));
    renderWithProviders(<UsersPage />);
    await screen.findByRole("link", { name: "John" });
    await userEvent.type(screen.getByLabelText("Search users"), "jo");
    await userEvent.selectOptions(screen.getByLabelText("Filter by role"), "viewer");
    await userEvent.selectOptions(screen.getByLabelText("Filter by status"), "suspended");
    await waitFor(() => {
      const last = seen[seen.length - 1];
      expect(last.get("q")).toBe("jo");
      expect(last.get("role")).toBe("viewer");
      expect(last.get("status")).toBe("suspended");
      expect(last.get("page_size")).toBe("25");
    });
  });

  it("adds a user as a pending invitation", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      listHandler([self]),
      http.post("*/api/v1/users/invite", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...user({ status: "pending", email: "new@example.test" }), entra_object_id: null, entra_tenant_id: "t" }, { status: 201 });
      }),
    );
    renderWithProviders(<UsersPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Add user" });
    expect(submit).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Microsoft Entra email or UPN"), "new@example.test");
    await userEvent.selectOptions(within(dialog).getByLabelText("Role"), "operator");
    await userEvent.click(submit);
    await waitFor(() => expect(body).toEqual({ email: "new@example.test", role_key: "operator", display_name: null }));
    expect(await screen.findByText("new@example.test added")).toBeInTheDocument();
  });

  it("shows the API error when adding an existing user", async () => {
    server.use(
      listHandler([self]),
      http.post("*/api/v1/users/invite", () =>
        HttpResponse.json({ error: { code: "USER_EXISTS", message: "A user with this email address already exists." } }, { status: 409 }),
      ),
    );
    renderWithProviders(<UsersPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Microsoft Entra email or UPN"), "john@example.test");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(await within(dialog).findByText("A user with this email address already exists.")).toBeInTheDocument();
  });

  it.each([
    ["Suspend", john, "suspend", "Suspend user", /John will no longer be able to access the Monitoring Platform/],
    ["Reactivate", sarah, "reactivate", "Reactivate user", /Sarah will be able to access the Monitoring Platform again/],
    ["Deactivate", john, "deactivate", "Deactivate user", /audit history are kept/],
  ] as const)("%s asks for confirmation, then calls the API", async (menuItem, target, action, confirm, text) => {
    let called: string | null = null;
    server.use(
      listHandler([self, target]),
      http.post(`*/api/v1/users/${target.id}/${action}`, () => {
        called = action;
        return HttpResponse.json({ ...target, entra_object_id: "oid", entra_tenant_id: "t" });
      }),
    );
    renderWithProviders(<UsersPage />);
    await userEvent.click(await screen.findByRole("button", { name: `Actions for ${target.display_name}` }));
    await userEvent.click(await screen.findByRole("menuitem", { name: menuItem }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(text)).toBeInTheDocument();
    expect(called).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: confirm }));
    await waitFor(() => expect(called).toBe(action));
  });

  it("only offers actions that apply to the user's status", async () => {
    server.use(listHandler([self, sarah]));
    renderWithProviders(<UsersPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Actions for Sarah" }));
    expect(await screen.findByRole("menuitem", { name: "Reactivate" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Suspend" })).not.toBeInTheDocument();
  });

  it("changes a user's role", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      listHandler([self, john]),
      http.patch("*/api/v1/users/u2", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...john, role_key: "operator", entra_object_id: "oid", entra_tenant_id: "t" });
      }),
    );
    renderWithProviders(<UsersPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Actions for John" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Change role" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(within(dialog).getByLabelText("Role"), "operator");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(body).toEqual({ role_key: "operator" }));
  });

  it("never offers roles above the signed-in user's own", async () => {
    // An Admin with user management (not the default model) still cannot pick Super Admin.
    server.use(
      http.get("*/api/v1/auth/me", () => HttpResponse.json(me({ role: "admin" }))),
      listHandler([john]),
    );
    renderWithProviders(<UsersPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const options = within(within(await screen.findByRole("dialog")).getByLabelText("Role")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Admin", "Operator", "Viewer"]);
  });

  it("shows API errors and an empty state", async () => {
    server.use(
      http.get("*/api/v1/users", () =>
        HttpResponse.json({ error: { code: "INTERNAL_ERROR", message: "Unexpected failure.", request_id: "req-1" } }, { status: 500 }),
      ),
    );
    renderWithProviders(<UsersPage />);
    expect(await screen.findByText("Unexpected failure.")).toBeInTheDocument();
    expect(screen.getByText("Request ID: req-1")).toBeInTheDocument();
  });

  it("is hidden from users without user management permission", async () => {
    let listed = false;
    server.use(
      http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)),
      http.get("*/api/v1/users", () => {
        listed = true;
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 25 });
      }),
    );
    renderWithProviders(<UsersPage />);
    expect(await screen.findByText("You do not have access to user management")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add user" })).not.toBeInTheDocument();
    expect(listed).toBe(false);
  });
});

describe("User detail page", () => {
  it("shows identity details and audit history to administrators", async () => {
    const detail: UserDetail = { ...john, entra_object_id: "0000-oid", entra_tenant_id: "1111-tenant" };
    server.use(
      http.get("*/api/v1/users/u2", () => HttpResponse.json(detail)),
      http.get("*/api/v1/users/u2/audit", () =>
        HttpResponse.json({
          items: [
            {
              id: "a1",
              user_id: "u1",
              actor: "admin@example.test",
              action: "user.invited",
              target_type: "user",
              target_id: "u2",
              result: "success",
              ip_address: "10.0.0.1",
              request_id: null,
              details: {},
              created_at: "2026-09-30T10:00:00Z",
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        }),
      ),
    );
    renderWithProviders(
      <Routes>
        <Route path="/settings/users/:userId" element={<UserDetailPage />} />
      </Routes>,
      { route: "/settings/users/u2" },
    );
    expect(await screen.findByRole("heading", { name: "John" })).toBeInTheDocument();
    expect(screen.getByText("0000-oid")).toBeInTheDocument();
    expect(screen.getByText("1111-tenant")).toBeInTheDocument();
    expect(await screen.findByText("user.invited")).toBeInTheDocument();
  });
});
