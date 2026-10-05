# Local development

## Options

| Mode | Command | Needs |
| --- | --- | --- |
| Docker Compose (recommended) | `docker compose up --build` or `scripts/dev.sh` / `scripts/dev.ps1` | Docker |
| Host processes | `scripts/dev.sh local` / `scripts/dev.ps1 local` | Python 3.12, Node.js 22+, a local PostgreSQL 16 |
| Against real Azure | `docker compose -f docker-compose.yml -f docker-compose.azure.yml up --build`, or host mode with `AZURE_PROVIDER=azure` | Entra app registrations and RBAC grants (see azure-setup.md) |

### Docker Compose

The stack consists of PostgreSQL 16, Redis 7, the backend (it runs `alembic upgrade head`, then Uvicorn), a Celery worker, Celery beat, and the frontend (nginx on port 8080, proxying `/api` to the backend). Only the web UI is published (`WEB_BIND:WEB_PORT`, default `0.0.0.0:8080`); PostgreSQL, Redis and the API are reachable only on the internal Compose network. The file works with both Compose v2 (`docker compose`) and the legacy `docker-compose` 1.27+, and requires a `.env` file (copy `.env.example`). Set `POSTGRES_PASSWORD` in `.env` on any shared machine (URL-safe characters only); it applies when the database volume is first created. With the default `AUTH_MODE=dev` there is no sign-in, so do not expose the port beyond a trusted network.

Defaults: `ENVIRONMENT=development`, `AUTH_MODE=dev`, `AZURE_PROVIDER=mock`, `TASK_BACKEND=celery`. Optional overrides come from a git-ignored `.env` file at the repository root. Copy `.env.example`, which contains placeholders only.

### Host processes

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt      # Linux/macOS: .venv/bin/pip
export ENVIRONMENT=development AUTH_MODE=dev AZURE_PROVIDER=mock TASK_BACKEND=inline
export DATABASE_URL=postgresql+asyncpg://monitoring:<password>@localhost:5432/monitoring
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
cp .env.example .env.local     # VITE_AUTH_MODE=dev for local work
npm ci
npm run dev                    # http://localhost:5173; /api, /health, /ready and /live proxy to VITE_BACKEND_URL (default http://localhost:8000)
```

With `TASK_BACKEND=inline`, jobs run as asyncio tasks inside the API process and Redis is not needed. Without `REDIS_URL`, the cache and rate-limit counters are held in process memory.

During development of this repository, local verification without Docker used an embedded PostgreSQL server purely as a test fixture. It is not part of the project and not a supported way to run it. Use Docker Compose or a normal local PostgreSQL 16 installation.

## Development-only modes

| Setting | Effect | Allowed in |
| --- | --- | --- |
| `AUTH_MODE=dev` | Every request is treated as the fixed user "Local developer (dev auth)", with role `DEV_USER_ROLE` (default `super_admin`). The UI shows a warning banner | `development`, `test` |
| `AZURE_PROVIDER=mock` | Deterministic demo estate (projects CRM, PRISM and DATACORE), synthetic metrics and logs, flagged `is_mock` and labelled "Demo data" in the UI | `development`, `test` |
| `TASK_BACKEND=inline` | In-process background jobs | `development`, `test` |

The settings class raises an error at start-up if any of these is used with `ENVIRONMENT=staging` or `production`.

In `AUTH_MODE=dev` the development user is created automatically as an active member. Admin-controlled access (invitations, suspension, the "Access not granted" page) applies in `AUTH_MODE=entra`. To exercise it without a tenant, run the backend tests (`tests/test_user_access.py`), which sign RS256 tokens with a test key. To try it in the browser, configure a real tenant as described in [entra-id.md](entra-id.md) and set `BOOTSTRAP_SUPER_ADMIN_OIDS` to your own object ID ([user-access-management.md](user-access-management.md)).

### Mock estate

| Mock subscription | ID | Contents |
| --- | --- | --- |
| Demo - Line of Business | `11111111-1111-4111-8111-111111111111` | CRM (dev, uat, prod) and PRISM (dev, prod) |
| Demo - Data Platform | `22222222-2222-4222-8222-222222222222` | DATACORE (dev, uat, prod), including Function Apps and Service Bus |
| Any other valid GUID | - | A small "INTERNAL" project (dev, prod) |

The mock tenant ID is `00000000-0000-4000-8000-00000000d3a0`. Resources are tagged `project` and `environment`, so they map onto projects you create with matching slugs (for example `crm`, `prism` and `datacore` with environments `dev`, `uat` and `prod`). The demo intentionally contains a CPU-pressured PRISM production workload, a Resource Health "Degraded" state on `app-prism-prod-uks`, and a recent HTTP 5xx increase on `app-crm-prod-uks`.

## Tests and checks

```bash
cd backend
ruff check app tests
ruff format --check app tests
mypy app
pytest                                         # SQLite, 131 tests
TEST_DATABASE_URL=postgresql+asyncpg://user@host:5432/db pytest   # PostgreSQL; the database is dropped and recreated per test
bandit -r app -ll
pip-audit -r requirements.txt
```

The test configuration sets `AUTH_MODE=entra`, signs RS256 tokens with a generated key and serves the JWKS through an `httpx.MockTransport`. Authentication is therefore exercised for real. Azure comes from the mock provider. The real service classes are covered by `tests/test_azure_services.py` with the SDK clients mocked.

```bash
cd frontend
npm run lint
npm run typecheck
npm test -- --run          # Vitest, Testing Library, msw
npm run build
npm audit --audit-level=high
```

### Migrations

```bash
cd backend
alembic revision --autogenerate -m "describe change"   # review the generated file
alembic upgrade head
alembic check                                          # fails if models and migrations differ
```

Never change a database schema by hand. CI runs upgrade, drift check and downgrade against PostgreSQL.
