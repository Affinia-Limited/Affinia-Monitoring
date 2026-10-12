import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { me } from "./fixtures";

/** Default handlers shared by all tests; individual tests add or override with server.use(). */
export const handlers = [
  http.get("*/api/v1/auth/me", () => HttpResponse.json(me())),
  http.get("*/api/v1/projects", () => HttpResponse.json([])),
  http.get("*/api/v1/alerts", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })),
  // Alert templates: nothing covered unless a test says otherwise.
  http.get("*/api/v1/alert-templates", () => HttpResponse.json([])),
  http.get("*/api/v1/alert-template-assignments", () => HttpResponse.json([])),
  http.get("*/api/v1/resources/:id/alert-plan", ({ params }) =>
    HttpResponse.json({ resource_id: params.id, monitor_key: null, template: null, assignment: null, rules: [] }),
  ),
];

export const server = setupServer(...handlers);
