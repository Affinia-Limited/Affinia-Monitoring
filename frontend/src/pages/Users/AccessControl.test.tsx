import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import { ErrorState } from "@/components/ui/states";
import { Sidebar } from "@/layouts/Sidebar";
import { AlertsPage } from "@/pages/Alerts/AlertsPage";
import { OverviewPage } from "@/pages/Dashboard/OverviewPage";
import { me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import type { AccessGrant, AssignableScope, UserDetail, UserOut } from "@/types/api";
import {
  type AccessSelection,
  EMPTY_SELECTION,
  grantsFromSelection,
  selectionError,
  selectionFromGrants,
  summariseGrants,
} from "@/utils/access";
import { AccessEditor } from "./AccessEditor";
import { UserDetailPage } from "./UserDetailPage";
import { UsersPage } from "./UsersPage";

const ADMIN_PERMISSIONS = [
  "dashboards:view",
  "dashboards:manage",
  "resources:view",
  "logs:view",
  "logs:run_kql",
  "azure:sync",
  "azure:connect",
  "projects:manage",
  "alerts:view",
  "alerts:manage",
  "alerts:acknowledge",
  "audit:view",
  "users:manage",
];

function grant(overrides: Partial<AccessGrant> = {}): AccessGrant {
  return {
    id: "g1",
    project_id: "p1",
    project_name: "CRM",
    environment_id: null,
    environment_name: null,
    resource_id: null,
    resource_name: null,
    ...overrides,
  };
}

/** An Admin who may only see CRM. */
const scopedAdmin = me({ role: "admin", permissions: ADMIN_PERMISSIONS, access: { unrestricted: false, grants: [grant()] } });

const fullScope: AssignableScope = {
  unrestricted: true,
  projects: [
    {
      id: "p1",
      name: "CRM",
      full: true,
      environments: [
        { id: "e1", name: "Development", kind: "development", full: true },
        { id: "e3", name: "Production", kind: "production", full: true },
      ],
    },
    { id: "p2", name: "PRISM", full: true, environments: [{ id: "e9", name: "Production", kind: "production", full: true }] },
  ],
};

/** What a granter limited to CRM / Production resources may grant. */
const partialScope: AssignableScope = {
  unrestricted: false,
  projects: [{ id: "p1", name: "CRM", full: false, environments: [{ id: "e3", name: "Production", kind: "production", full: false }] }],
};

function serveScope(scope: AssignableScope) {
  const searches: string[] = [];
  server.use(
    http.get("*/api/v1/users/assignable-scope", () => HttpResponse.json(scope)),
    http.get("*/api/v1/users/assignable-scope/environments/:env/resources", ({ request }) => {
      searches.push(new URL(request.url).searchParams.get("q") ?? "");
      return HttpResponse.json([
        { id: "r1", name: "app-crm-prod-uks", type_display_name: "App Service", monitored: true },
        { id: "r2", name: "nic-crm-prod", type_display_name: "Network interface", monitored: false },
      ]);
    }),
  );
  return searches;
}

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
    last_login_at: null,
    invited_at: null,
    invitation_expires_at: null,
    activated_at: "2026-09-30T11:00:00Z",
    deactivated_at: null,
    created_at: "2026-09-30T10:00:00Z",
    created_by_name: "Test Admin",
    access: { unrestricted: false, grants: [grant()] },
    ...overrides,
  };
}

function Harness({ isSuperAdmin = false, onValue }: { isSuperAdmin?: boolean; onValue: (s: AccessSelection) => void }) {
  const [value, setValue] = useState<AccessSelection>(EMPTY_SELECTION);
  return (
    <AccessEditor
      value={value}
      isSuperAdmin={isSuperAdmin}
      onChange={(next) => {
        setValue(next);
        onValue(next);
      }}
    />
  );
}

describe("access selection helpers", () => {
  it("produces the minimal grants and reads them back", () => {
    const selection: AccessSelection = {
      all: false,
      projects: { p1: "all", p2: { e9: "all", e8: { r1: "app-a", r2: "app-b" } } },
    };
    const grants = grantsFromSelection(selection);
    expect(grants).toEqual([
      { project_id: "p1" },
      { project_id: "p2", environment_id: "e9" },
      { project_id: "p2", environment_id: "e8", resource_id: "r1" },
      { project_id: "p2", environment_id: "e8", resource_id: "r2" },
    ]);
    const back = selectionFromGrants(
      grants.map((g) => ({ project_id: g.project_id, environment_id: g.environment_id ?? null, resource_id: g.resource_id ?? null, resource_name: g.resource_id ?? null })),
    );
    expect(grantsFromSelection(back)).toEqual(grants);
    expect(grantsFromSelection({ all: true, projects: {} })).toEqual([{ project_id: null }]);
  });

  it("validates incomplete selections", () => {
    expect(selectionError(EMPTY_SELECTION, false)).toMatch(/at least one project/);
    expect(selectionError(EMPTY_SELECTION, true)).toBeNull();
    expect(selectionError({ all: false, projects: { p1: {} } }, false)).toMatch(/environment/);
    expect(selectionError({ all: false, projects: { p1: { e1: {} } } }, false)).toMatch(/resource/);
    expect(selectionError({ all: false, projects: { p1: { e1: { r1: "a" } } } }, false)).toBeNull();
  });

  it("summarises grants in plain English", () => {
    expect(summariseGrants([grant({ project_id: null })])).toBe("All projects");
    expect(summariseGrants([])).toBe("No access");
    expect(
      summariseGrants([
        grant(),
        grant({ id: "g2", project_id: "p2", project_name: "PRISM", environment_id: "e9", environment_name: "Production", resource_id: "r1" }),
        grant({ id: "g3", project_id: "p2", project_name: "PRISM", environment_id: "e9", environment_name: "Production", resource_id: "r2" }),
      ]),
    ).toBe("CRM: all environments · PRISM / Production: 2 resources");
  });
});

describe("Access editor", () => {
  it("is not needed for Super Admins", async () => {
    renderWithProviders(<Harness isSuperAdmin onValue={() => {}} />);
    expect(screen.getByText("Super Admins always have access to everything.")).toBeInTheDocument();
  });

  it("drills down from project to environment to specific resources", async () => {
    const searches = serveScope(fullScope);
    let latest: AccessSelection = EMPTY_SELECTION;
    renderWithProviders(<Harness onValue={(s) => (latest = s)} />);

    await userEvent.click(await screen.findByRole("checkbox", { name: "CRM" }));
    expect(latest).toEqual({ all: false, projects: { p1: "all" } });

    const envGroup = screen.getByRole("radiogroup", { name: "Environments in CRM" });
    await userEvent.click(within(envGroup).getByRole("radio", { name: "Specific environments" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Production" }));
    expect(latest).toEqual({ all: false, projects: { p1: { e3: "all" } } });

    const resGroup = screen.getByRole("radiogroup", { name: "Resources in CRM / Production" });
    await userEvent.click(within(resGroup).getByRole("radio", { name: "Specific resources" }));
    // Resources load only now, for this environment.
    const list = await screen.findByRole("list", { name: "Resources in CRM / Production" });
    expect(within(list).getByText(/not monitored/)).toBeInTheDocument();
    await userEvent.click(within(list).getByRole("checkbox", { name: /app-crm-prod-uks/ }));
    expect(grantsFromSelection(latest)).toEqual([{ project_id: "p1", environment_id: "e3", resource_id: "r1" }]);
    expect(screen.getByText(/CRM \/ Production: 1 resource$/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Search resources in CRM / Production"), "app");
    await waitFor(() => expect(searches).toContain("app"));
  });

  it("only offers what the signed-in admin may grant", async () => {
    serveScope(partialScope);
    renderWithProviders(<Harness onValue={() => {}} />);
    await userEvent.click(await screen.findByRole("checkbox", { name: "CRM" }));
    expect(screen.queryByRole("radio", { name: "All projects" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "All environments" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Production" }));
    expect(screen.queryByRole("radio", { name: "All resources" })).not.toBeInTheDocument();
    expect(await screen.findByRole("list", { name: "Resources in CRM / Production" })).toBeInTheDocument();
  });
});

describe("Users with scoped access", () => {
  it("invites a user to specific environments", async () => {
    serveScope(fullScope);
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get("*/api/v1/users", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 25 })),
      http.post("*/api/v1/users/invite", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...user({ status: "pending", email: "new@example.test" }), entra_object_id: null, entra_tenant_id: "t" }, { status: 201 });
      }),
    );
    renderWithProviders(<UsersPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Microsoft Entra email or UPN"), "new@example.test");

    // Nothing chosen yet: the form explains what is missing instead of sending.
    await userEvent.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(await within(dialog).findByText(/Choose at least one project/)).toBeInTheDocument();
    expect(body).toBeNull();

    await userEvent.click(within(dialog).getByRole("checkbox", { name: "PRISM" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Add user" }));
    await waitFor(() =>
      expect(body).toEqual({ email: "new@example.test", role_key: "viewer", display_name: null, grants: [{ project_id: "p2" }] }),
    );
  });

  it("shows each user's access in the table", async () => {
    server.use(
      http.get("*/api/v1/users", () =>
        HttpResponse.json({
          items: [user(), user({ id: "u3", display_name: "Sarah", access: { unrestricted: true, grants: [grant({ project_id: null })] } })],
          total: 2,
          page: 1,
          page_size: 25,
        }),
      ),
    );
    renderWithProviders(<UsersPage />);
    const john = (await screen.findByRole("link", { name: "John" })).closest("tr") as HTMLElement;
    expect(within(john).getByText("CRM: all environments")).toBeInTheDocument();
    const sarah = screen.getByRole("link", { name: "Sarah" }).closest("tr") as HTMLElement;
    expect(within(sarah).getByText("All projects")).toBeInTheDocument();
  });

  it("edits a user's access and explains a refusal", async () => {
    serveScope(fullScope);
    const detail: UserDetail = { ...user(), entra_object_id: null, entra_tenant_id: "t" };
    const puts: unknown[] = [];
    let refuse = true;
    server.use(
      http.get("*/api/v1/users/u2", () => HttpResponse.json(detail)),
      http.get("*/api/v1/users/u2/audit", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })),
      http.put("*/api/v1/users/u2/access", async ({ request }) => {
        puts.push(await request.json());
        return refuse
          ? HttpResponse.json({ error: { code: "ACCESS_OUT_OF_SCOPE", message: "You can only grant access you have yourself." } }, { status: 403 })
          : HttpResponse.json(detail);
      }),
    );
    renderWithProviders(
      <Routes>
        <Route path="/settings/users/:userId" element={<UserDetailPage />} />
      </Routes>,
      { route: "/settings/users/u2" },
    );
    expect(await screen.findByText("Projects and resources")).toBeInTheDocument();
    expect(screen.getByText("CRM: all environments", { selector: "li" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Edit access/ }));
    const dialog = await screen.findByRole("dialog");
    // Starts from the current grants.
    expect(await within(dialog).findByRole("checkbox", { name: "CRM" })).toBeChecked();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "PRISM" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save access" }));
    expect(await within(dialog).findByText("You can only grant access you have yourself.")).toBeInTheDocument();
    expect(puts).toEqual([{ grants: [{ project_id: "p1" }, { project_id: "p2" }] }]);

    refuse = false;
    await userEvent.click(within(dialog).getByRole("button", { name: "Save access" }));
    expect(await screen.findByText("Access updated for John")).toBeInTheDocument();
  });
});

describe("Scope-aware navigation", () => {
  it("hides organisation-wide areas from scoped admins but shows Users", async () => {
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(scopedAdmin)));
    renderWithProviders(<Sidebar collapsed={false} />);
    expect(await screen.findByRole("link", { name: "Users" })).toHaveAttribute("href", "/settings/users");
    expect(screen.queryByRole("link", { name: "Azure Connections" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit log" })).not.toBeInTheDocument();
  });

  it("hides notification settings from scoped admins, even by URL", async () => {
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(scopedAdmin)));
    renderWithProviders(<AlertsPage />, { route: "/alerts?tab=teams" });
    expect(await screen.findByRole("tab", { name: "Alert templates" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Alerts" })).toHaveAttribute("aria-selected", "true");
    for (const name of ["Microsoft Teams", "Email notifications", "Notification channels"]) {
      expect(screen.queryByRole("tab", { name })).not.toBeInTheDocument();
    }
  });

  it("tells a user with no access what to do", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json(me({ role: "viewer", permissions: ["dashboards:view", "resources:view", "alerts:view"], access: { unrestricted: false, grants: [] } })),
      ),
    );
    renderWithProviders(<OverviewPage />);
    expect(await screen.findByText("You don't have access to any projects yet")).toBeInTheDocument();
  });

  it("explains organisation-wide refusals", () => {
    const error = new ApiError(403, { code: "SCOPE_REQUIRED", message: "This needs access to all projects." });
    renderWithProviders(<ErrorState error={error} />);
    expect(screen.getByText("This area needs access to all projects")).toBeInTheDocument();
    expect(screen.getByText("This needs access to all projects.")).toBeInTheDocument();
  });
});
