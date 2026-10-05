import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { me } from "./fixtures";

/** Default handlers shared by all tests; individual tests add or override with server.use(). */
export const handlers = [
  http.get("*/api/v1/auth/me", () => HttpResponse.json(me())),
  http.get("*/api/v1/projects", () => HttpResponse.json([])),
  http.get("*/api/v1/alerts", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })),
];

export const server = setupServer(...handlers);
