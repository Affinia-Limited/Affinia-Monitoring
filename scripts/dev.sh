#!/usr/bin/env bash
# Local development helper.
#   scripts/dev.sh           docker compose stack (Postgres, Redis, API, worker, beat, web) on http://localhost:8080
#   scripts/dev.sh local     run API + frontend on the host against a local PostgreSQL (no Docker)
#   scripts/dev.sh down      stop the docker compose stack
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mode="${1:-docker}"

case "$mode" in
  docker)
    echo "Starting the stack: http://localhost:8080 (API docs: http://localhost:8000/api/docs)"
    exec docker compose up --build
    ;;
  down)
    exec docker compose down
    ;;
  local)
    # Requires a local PostgreSQL with a 'monitoring' database and user (see docs/local-development.md).
    export ENVIRONMENT="${ENVIRONMENT:-development}"
    export AUTH_MODE="${AUTH_MODE:-dev}"
    export AZURE_PROVIDER="${AZURE_PROVIDER:-mock}"
    export TASK_BACKEND="${TASK_BACKEND:-inline}"
    export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://monitoring:monitoring@localhost:5432/monitoring}"
    PY="$ROOT/backend/.venv/bin/python"
    [[ -x "$PY" ]] || PY="$ROOT/backend/.venv/Scripts/python.exe"
    if [[ ! -x "$PY" ]]; then
      echo "Create the backend virtualenv first: cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
      exit 1
    fi
    (cd backend && "$PY" -m alembic upgrade head)
    (cd backend && "$PY" -m uvicorn app.main:app --reload --port 8000) &
    API_PID=$!
    trap 'kill $API_PID 2>/dev/null || true' EXIT
    (cd frontend && { [[ -d node_modules ]] || npm install; } && npm run dev)
    ;;
  *)
    echo "Usage: $0 [docker|local|down]" >&2
    exit 2
    ;;
esac
