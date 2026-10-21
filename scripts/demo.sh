#!/usr/bin/env bash
# Serve Longevidence temporarily through a Cloudflare quick tunnel (no account, random *.trycloudflare.com URL, gone on Ctrl-C).
#
# Only the Next.js app is tunneled. Every page fetches data server-side, so the browser never talks to the API; the API listens on
# 127.0.0.1 only and its unauthenticated ingestion endpoints are never exposed (the web app's ingest proxy and the free-form page's ingest offer are switched off with INGEST_UI=off).
# Separate ports and build directory so this can run next to `make api` / `make web`.
#   scripts/demo.sh              build, start API + web, open the tunnel
#   scripts/demo.sh --no-tunnel  start API + web locally only (smoke test)
set -euo pipefail
cd "$(dirname "$0")/.."
API_PORT="${DEMO_API_PORT:-8011}"; WEB_PORT="${DEMO_WEB_PORT:-3011}"
NO_TUNNEL=0; [[ "${1:-}" == "--no-tunnel" ]] && NO_TUNNEL=1

if [[ $NO_TUNNEL -eq 0 ]] && ! command -v cloudflared >/dev/null; then
  echo "cloudflared not found. Install it first:  brew install cloudflared" >&2; exit 1
fi
for p in "$API_PORT" "$WEB_PORT"; do
  if lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then echo "port $p is already in use (set DEMO_API_PORT / DEMO_WEB_PORT)" >&2; exit 1; fi
done

pids=()
cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

echo "building frontend..."
( cd frontend && NEXT_DIST_DIR=.next-demo npm run build >/tmp/longevidence-demo-build.log 2>&1 ) || { tail -20 /tmp/longevidence-demo-build.log; exit 1; }

( cd backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >/tmp/longevidence-demo-api.log 2>&1 ) & pids+=($!)
( cd frontend && API_URL="http://127.0.0.1:$API_PORT" INGEST_UI=off NEXT_DIST_DIR=.next-demo exec npx next start -H 127.0.0.1 -p "$WEB_PORT" >/tmp/longevidence-demo-web.log 2>&1 ) & pids+=($!)

for i in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$WEB_PORT/" >/dev/null 2>&1 && break
  sleep 1
  [[ $i -eq 40 ]] && { echo "web app did not start; see /tmp/longevidence-demo-web.log" >&2; exit 1; }
done
echo "local demo: http://127.0.0.1:$WEB_PORT  (API on 127.0.0.1:$API_PORT, not exposed)"

if [[ $NO_TUNNEL -eq 1 ]]; then echo "press Ctrl-C to stop"; wait; exit 0; fi
echo "starting tunnel (Ctrl-C stops everything)..."
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$WEB_PORT"
