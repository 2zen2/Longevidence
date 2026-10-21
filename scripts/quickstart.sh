#!/usr/bin/env bash
# One command from a fresh checkout to a running app: install, database, example data, then API + web.
# Safe to re-run; each step is skipped when already done. Ctrl-C stops both servers.
set -euo pipefail
cd "$(dirname "$0")/.."
API_PORT="${API_PORT:-8010}"; WEB_PORT="${WEB_PORT:-3010}"
step() { printf '\n==> %s\n' "$1"; }

step "prerequisites"
need() { command -v "$1" >/dev/null || { echo "missing: $1 ($2)" >&2; exit 1; }; }
need python3 "Python 3.11+"; need node "Node 20+"; need npm "Node 20+"; need psql "the PostgreSQL client"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11+ is required (found $(python3 -V))" >&2; exit 1; }
[[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ]] || { echo "Node 20+ is required (found $(node -v))" >&2; exit 1; }
[[ -f seed/data.sql.gz || -n "${SEED_URL:-}" ]] || grep -q '^SEED_URL=.\+' .env 2>/dev/null || echo "note: seed/data.sql.gz not found; the seed step needs it (or SEED_URL in .env)" >&2

step "config"
[[ -f .env ]] || { cp .env.example .env; echo "created .env from .env.example"; }
DB="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
echo "database: $(echo "$DB" | sed -E 's#(://[^:/@]+):[^@]*@#\1:****@#')"

step "dependencies"
[[ -d backend/.venv && -d frontend/node_modules ]] && echo "already installed" || make setup

step "database"
if ! DBERR="$(psql "$DB" -tAc 'SELECT 1' 2>&1 >/dev/null)"; then
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    make up
    DBERR="$(psql "$DB" -tAc 'SELECT 1' 2>&1 >/dev/null)" || {
      echo "The Docker database is up but $DB does not connect to it:" >&2
      echo "  $DBERR" >&2
      echo "Another Postgres is probably using that port. Change the port in docker-compose.yml and DATABASE_URL (.env), then re-run." >&2
      exit 1
    }
  else
    cat >&2 <<MSG
Cannot reach the database in .env, and Docker is not available (not installed, or Docker Desktop is not running).
Pick one:
  1. Docker:         start Docker Desktop, wait until it is running, then re-run 'make quickstart'
  2. Local Postgres: createdb longevidence_db
                     set DATABASE_URL=postgresql://localhost/longevidence_db in .env, then re-run 'make quickstart'
MSG
    exit 1
  fi
fi
make migrate
scripts/seed.sh

for p in "$API_PORT" "$WEB_PORT"; do
  if lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then echo "port $p is already in use (set API_PORT / WEB_PORT)" >&2; exit 1; fi
done
pids=(); trap 'for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done' EXIT INT TERM
step "starting"
( cd backend && exec .venv/bin/uvicorn app.main:app --port "$API_PORT" ) & pids+=($!)
( cd frontend && API_URL="http://127.0.0.1:$API_PORT" exec npx next dev -p "$WEB_PORT" ) & pids+=($!)
# Free-form questions and semantic search need embeddings, which the seed does not include. Building them takes a while on a CPU
# (papers first, about 2 minutes; passages after, tens of minutes), so it runs in the background while the app is already usable.
# Resumable; the first run downloads a ~64 MB model. SKIP_INDEX=1 skips it.
if [[ "${SKIP_INDEX:-0}" != "1" ]]; then
  LOG="${TMPDIR:-/tmp}/longevidence-index.log"
  ( cd backend && exec .venv/bin/python -m app.search.build >"$LOG" 2>&1 ) & pids+=($!)
  echo "Search index is building in the background (log: $LOG). Keyword search works meanwhile; semantic search improves as it finishes."
fi
echo "Open http://localhost:$WEB_PORT   (Ctrl-C to stop)"
wait
