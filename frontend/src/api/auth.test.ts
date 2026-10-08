import { InteractionRequiredAuthError, type PublicClientApplication } from "@azure/msal-browser";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/server";
import { setMsalForTesting } from "./auth";
import { ApiError, isReauthenticating } from "./client";
import { endpoints } from "./endpoints";

const account = { homeAccountId: "h", environment: "login.microsoftonline.com", tenantId: "t", username: "user@example.com", localAccountId: "l" };

/** A stand-in MSAL client: redirects are recorded, never performed. */
function fakeMsal(token: () => Promise<{ accessToken: string }>) {
  const msal = {
    getActiveAccount: () => account,
    getAllAccounts: () => [account],
    acquireTokenSilent: vi.fn(token),
    acquireTokenRedirect: vi.fn(() => new Promise<void>(() => {})),
    loginRedirect: vi.fn(() => new Promise<void>(() => {})),
  };
  setMsalForTesting(msal as unknown as PublicClientApplication);
  return msal;
}

/** Records the Authorization header of every projects request that reaches the API. */
function recordProjects(status = 200) {
  const seen: (string | null)[] = [];
  server.use(
    http.get("*/api/v1/projects", ({ request }) => {
      seen.push(request.headers.get("authorization"));
      return status === 200
        ? HttpResponse.json([])
        : HttpResponse.json({ error: { code: "UNAUTHENTICATED", message: "The access token has expired." } }, { status });
    }),
  );
  return seen;
}

afterEach(() => {
  setMsalForTesting(null);
  window.sessionStorage.clear();
});

describe("API authentication", () => {
  it("sends the access token", async () => {
    fakeMsal(async () => ({ accessToken: "tok" }));
    const seen = recordProjects();
    await endpoints.projects();
    expect(seen).toEqual(["Bearer tok"]);
  });

  it("starts one sign-in for many requests and never sends them without a token", async () => {
    const msal = fakeMsal(async () => {
      throw new InteractionRequiredAuthError("interaction_required");
    });
    const seen = recordProjects();

    const results = await Promise.allSettled([endpoints.projects(), endpoints.projects(), endpoints.projects()]);

    expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
    expect(seen).toEqual([]);
    for (const r of results) {
      expect(r.status).toBe("rejected");
      expect(isReauthenticating((r as PromiseRejectedResult).reason)).toBe(true);
    }
  });

  it("signs in again once when the API rejects the token", async () => {
    const msal = fakeMsal(async () => ({ accessToken: "expired" }));
    recordProjects(401);

    const results = await Promise.allSettled([endpoints.projects(), endpoints.projects()]);

    expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
    const reason = (results[0] as PromiseRejectedResult).reason as ApiError;
    expect(reason).toBeInstanceOf(ApiError);
    expect(reason.code).toBe("REAUTHENTICATING");
    expect(reason.message).toMatch(/Signing you in again/);
  });

  it("does not loop when the API keeps refusing fresh tokens", async () => {
    const msal = fakeMsal(async () => ({ accessToken: "refused" }));
    recordProjects(401);
    await expect(endpoints.projects()).rejects.toMatchObject({ code: "REAUTHENTICATING" });

    // Back from the sign-in, the API still says 401 (e.g. a wrong audience): show it, do not redirect again.
    setMsalForTesting(msal as unknown as PublicClientApplication);
    await expect(endpoints.projects()).rejects.toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
    expect(msal.acquireTokenRedirect).toHaveBeenCalledTimes(1);
  });

  it("leaves dev sign-in alone: a 401 is reported, not redirected", async () => {
    recordProjects(401);
    await expect(endpoints.projects()).rejects.toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
  });
});
