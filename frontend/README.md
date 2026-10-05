# Frontend

React + TypeScript + Vite single-page application for the Azure Monitoring Platform.

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Dev server on http://localhost:5173 (proxies `/api`, `/health`, `/ready`, `/live` to the backend) |
| `npm run build` | Type-check and production build to `dist/` |
| `npm run lint` | ESLint (flat config, typescript-eslint, react-hooks) |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm test -- --run` | Vitest + Testing Library + msw |

## Environment variables

Copy `.env.example` to `.env.local`. Only non-secret values belong here; everything is embedded in the public bundle.

| Variable | Description |
| --- | --- |
| `VITE_AUTH_MODE` | `entra` (Microsoft Entra ID via MSAL) or `dev` (no sign-in; only works with a backend in `AUTH_MODE=dev`) |
| `VITE_ENTRA_CLIENT_ID` | SPA app registration client ID |
| `VITE_ENTRA_TENANT_ID` | Entra tenant ID |
| `VITE_ENTRA_API_SCOPE` | API scope, e.g. `api://<api-client-id>/access_as_user` |
| `VITE_ENTRA_REDIRECT_URI` | Redirect URI registered on the SPA app (defaults to the current origin) |
| `VITE_BACKEND_URL` | Backend URL for the Vite dev proxy (default `http://localhost:8000`) |

## Authentication and security

- MSAL redirect flow; tokens are cached in `sessionStorage` by MSAL, never in `localStorage`, and never logged.
- An Axios interceptor acquires a token silently for every request and falls back to an interactive redirect.
- After sign-in the app calls `POST /api/v1/auth/session` once so the login is audited.
- Permissions from `/auth/me` only hide controls. The API enforces every permission.
- API errors are shown as the structured `message` plus `request_id`. Raw error text is never displayed.
- There are no inline scripts and no `eval`, so the app works under a strict Content Security Policy.

## Structure

```
src/
  api/            Axios client, MSAL helpers, typed endpoint functions
  components/     Shared components (ui/ = shadcn-style primitives on Radix, widgets/ = dashboard widgets)
  hooks/          useMe/usePermission, useMetrics, useLogQuery, useChartColors, useDebounce
  layouts/        App shell: sidebar, top bar, global search
  pages/          Dashboard (overview), Projects, Resources, Dashboards, Alerts, Logs, AzureConnections, Settings
  routes/         Route table
  stores/         URL-synced global filters (project, environment, time range) and theme
  types/          TypeScript mirrors of the backend schemas
  utils/          Formatting (en-GB, DD/MM/YYYY), time ranges, env
  test/           msw server, fixtures, render helper
```

## Dashboards

Dashboards come from backend templates (`GET /dashboards/by-resource/{id}`). `DashboardRenderer` lays widgets out on a 12-column grid. `components/widgets/registry.tsx` maps each `widget_type` to a component, and unknown types render a neutral placeholder. Metric widgets request all of their metric keys in a single `/resources/{id}/metrics` call. When Azure has no data they show "Not available for this resource" and never substitute generated values. Whenever the backend flags a response `is_mock`, the page shows a "Demo data" badge.
