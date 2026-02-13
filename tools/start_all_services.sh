#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_PORT="${APP_PORT:-8080}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

pick_port() {
  local preferred="$1"
  local candidates=("$preferred" 8081 8082 8083)
  for p in "${candidates[@]}"; do
    if ! (echo > /dev/tcp/127.0.0.1/"$p") >/dev/null 2>&1; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

echo "[1/6] Preparing environment file..."
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

set -a
source .env
set +a

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set in .env" >&2
  exit 1
fi

# SQLAlchemy URL -> libpq URL for psql/pg_isready.
PSQL_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
DB_NAME="$(python3 - <<'PY'
import os
from urllib.parse import urlparse
u = os.environ.get("DATABASE_URL", "")
p = urlparse(u)
print((p.path or "").lstrip("/"))
PY
)"

echo "[2/6] Checking local PostgreSQL service (no Docker)..."
if command -v pg_isready >/dev/null 2>&1; then
  if ! pg_isready -h localhost -p 5432 -U postgres -d "${DB_NAME:-postgres}" >/dev/null 2>&1; then
    echo "Local PostgreSQL is not ready on localhost:5432."
    echo "Start your local DB service first, then rerun this script."
    exit 1
  fi
else
  if ! (echo > /dev/tcp/127.0.0.1/5432) >/dev/null 2>&1; then
    echo "Cannot connect to local PostgreSQL on localhost:5432."
    echo "Start your local DB service first, then rerun this script."
    exit 1
  fi
fi

echo "[3/6] Waiting for PostgreSQL to accept connections..."
for i in {1..30}; do
  if command -v psql >/dev/null 2>&1 && psql "$PSQL_URL" -c "SELECT 1;" >/dev/null 2>&1; then
    break
  fi
  if [[ ! -x "$(command -v psql || true)" ]]; then
    break
  fi
  sleep 1
  if [[ "$i" -eq 30 ]]; then
    echo "PostgreSQL did not become ready in time." >&2
    echo "Tried URL: ${PSQL_URL}" >&2
    echo "Tip: verify credentials and DB existence, e.g. psql \"${PSQL_URL}\" -c 'SELECT 1;'" >&2
    exit 1
  fi
done

echo "[4/6] Creating virtual environment and installing dependencies..."
if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
source .venv/bin/activate
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
python -m pip install --upgrade pip
python -m pip install -e .

echo "[5/6] Running migrations..."
if ! alembic -c app/db/migrations/alembic.ini upgrade head; then
  HAS_FACTORIES="$(psql "$PSQL_URL" -tAc "SELECT to_regclass('public.factories') IS NOT NULL;" 2>/dev/null | tr -d '[:space:]' || true)"
  HAS_ALEMBIC_VERSION="$(psql "$PSQL_URL" -tAc "SELECT to_regclass('public.alembic_version') IS NOT NULL;" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ "$HAS_FACTORIES" == "t" && "$HAS_ALEMBIC_VERSION" == "f" ]]; then
    echo "Existing schema detected without alembic version table; stamping head..."
    alembic -c app/db/migrations/alembic.ini stamp head
  else
    echo "Migration failed and could not auto-recover." >&2
    echo "Tip: if this is a disposable DB, reset it and rerun." >&2
    exit 1
  fi
fi

if ! SELECTED_PORT="$(pick_port "$APP_PORT")"; then
  echo "No free port found in {${APP_PORT},8081,8082,8083}. Stop an existing app and retry." >&2
  exit 1
fi
APP_PORT="$SELECTED_PORT"
echo "[6/6] Starting application on port ${APP_PORT}..."
export APP_PORT
python -m app.main
