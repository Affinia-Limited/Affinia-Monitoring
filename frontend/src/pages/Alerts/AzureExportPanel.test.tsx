import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { deployCommand, parseRecipients } from "@/api/azureExport";
import { project, viewer } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { AzureExportPanel } from "./AzureExportPanel";

const exported = {
  templates: [
    {
      subscription_id: "11111111-1111-4111-8111-111111111111",
      subscription_name: "Demo - Line of Business",
      filename: "azure-alerts-demo-line-of-business-11111111",
      alert_count: 42,
      template: { $schema: "x", resources: [] },
    },
  ],
  skipped: [{ resource_name: "app-x", rule: "Health threshold (warning): Plan CPU", reason: "The related app service plan has not been discovered." }],
  resources: 12,
};

afterEach(() => vi.restoreAllMocks());

function readText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

describe("parseRecipients", () => {
  it("splits, lower-cases, de-duplicates and separates invalid entries", () => {
    expect(parseRecipients("Ops@Contoso.com, ops@contoso.com;\noncall@contoso.com  bad")).toEqual({
      valid: ["ops@contoso.com", "oncall@contoso.com"],
      invalid: ["bad"],
    });
  });

  it("builds an az CLI command for the template", () => {
    expect(deployCommand(exported.templates[0])).toBe(
      "az deployment group create --resource-group <your-resource-group> --subscription 11111111-1111-4111-8111-111111111111 --template-file azure-alerts-demo-line-of-business-11111111.json",
    );
  });
});

describe("AzureExportPanel", () => {
  it("generates templates for the chosen scope and recipients", async () => {
    let params: URLSearchParams | null = null;
    server.use(
      http.get("*/api/v1/projects", () => HttpResponse.json([project()])),
      http.get("*/api/v1/alert-rules/azure-export", ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json(exported);
      }),
    );
    renderWithProviders(<AzureExportPanel />);

    await screen.findByRole("option", { name: "Project One" });
    await userEvent.selectOptions(screen.getByLabelText("Project"), "p1");
    await userEvent.click(screen.getByLabelText("Custom alert rules"));
    await userEvent.type(screen.getByLabelText("Email recipients"), "Ops@Contoso.com, oncall@contoso.com");
    await userEvent.type(screen.getByLabelText("Action group name (optional)"), "prod-oncall");
    await userEvent.click(screen.getByRole("button", { name: "Generate templates" }));

    expect(await screen.findByText(/42 alert rules · subscription 11111111/)).toBeInTheDocument();
    expect(params!.get("project_id")).toBe("p1");
    expect(params!.get("include_rules")).toBe("false");
    expect(params!.get("include_health")).toBe("true");
    expect(params!.get("recipients")).toBe("ops@contoso.com,oncall@contoso.com");
    expect(params!.get("action_group_name")).toBe("prod-oncall");
    expect(screen.getByText(/on 12 resources/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download template for Demo - Line of Business" })).toBeInTheDocument();

    // Skipped rules are explained on demand.
    await userEvent.click(screen.getByRole("button", { name: /1 rule could not be exported/ }));
    expect(screen.getByText(/has not been discovered/)).toBeInTheDocument();
  });

  it("downloads the template as pretty-printed JSON", async () => {
    server.use(http.get("*/api/v1/alert-rules/azure-export", () => HttpResponse.json(exported)));
    const created = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderWithProviders(<AzureExportPanel />);

    await userEvent.click(await screen.findByRole("button", { name: "Generate templates" }));
    await userEvent.click(await screen.findByRole("button", { name: "Download template for Demo - Line of Business" }));

    expect(click).toHaveBeenCalledTimes(1);
    const blob = created.mock.calls[0][0] as Blob;
    expect(blob.type).toBe("application/json");
    expect(await readText(blob)).toBe(JSON.stringify(exported.templates[0].template, null, 2) + "\n");
  });

  it("refuses invalid recipients before calling the API", async () => {
    const calls: string[] = [];
    server.use(
      http.get("*/api/v1/alert-rules/azure-export", ({ request }) => {
        calls.push(request.url);
        return HttpResponse.json(exported);
      }),
    );
    renderWithProviders(<AzureExportPanel />);
    await userEvent.type(await screen.findByLabelText("Email recipients"), "ops@contoso.com, not-an-email");

    expect(screen.getByRole("alert")).toHaveTextContent("not-an-email");
    expect(screen.getByRole("button", { name: "Generate templates" })).toBeDisabled();
    expect(calls).toEqual([]);
  });

  it("shows API errors and an empty result clearly", async () => {
    server.use(
      http.get("*/api/v1/alert-rules/azure-export", () =>
        HttpResponse.json({ error: { code: "NOT_FOUND", message: "Project not found." } }, { status: 404 }),
      ),
    );
    renderWithProviders(<AzureExportPanel />);
    await userEvent.click(await screen.findByRole("button", { name: "Generate templates" }));
    expect(await screen.findByText("Project not found.")).toBeInTheDocument();

    server.use(http.get("*/api/v1/alert-rules/azure-export", () => HttpResponse.json({ templates: [], skipped: [], resources: 0 })));
    await userEvent.click(screen.getByRole("button", { name: "Generate templates" }));
    const status = await screen.findByText(/No alert rules apply to this scope/);
    expect(within(status.parentElement as HTMLElement).queryByRole("button", { name: /Download/ })).toBeNull();
  });

  it("is hidden from users who cannot manage alerts", async () => {
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json(viewer)));
    const { client } = renderWithProviders(<AzureExportPanel />);
    await waitFor(() => expect(client.getQueryData(["me"])).toBeDefined());
    expect(screen.queryByText("Export to Azure Monitor")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate templates" })).not.toBeInTheDocument();
  });
});
