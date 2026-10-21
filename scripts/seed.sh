#!/usr/bin/env bash
# Load the bundled example dataset (seed/data.sql.gz) into an empty database. Safe to re-run: does nothing if data is already there.
# The file is kept out of git history; if it is missing it is downloaded from SEED_URL (env var or .env), e.g. a GitHub release asset.
set -euo pipefail
cd "$(dirname "$0")/.."
getenv() { [[ -n "${!1:-}" ]] && echo "${!1}" || { [[ -f .env ]] && grep -E "^$1=" .env | head -1 | cut -d= -f2- || true; }; }
DB="$(getenv DATABASE_URL)"; [[ -n "$DB" ]] || { echo "DATABASE_URL is not set (copy .env.example to .env)" >&2; exit 1; }
FILE=seed/data.sql.gz

n="$(psql "$DB" -tAc 'SELECT count(*) FROM papers' 2>/dev/null || echo missing)"
[[ "$n" == "missing" ]] && { echo "Database is not ready. Run 'make migrate' first (and 'make up' if you use Docker)." >&2; exit 1; }
if [[ "$n" != "0" ]]; then echo "Database already has data ($n papers); skipping seed."; exit 0; fi

if [[ ! -f "$FILE" ]]; then
  URL="$(getenv SEED_URL)"
  [[ -n "$URL" ]] || { echo "$FILE not found and SEED_URL is not set. Download the seed file into seed/ or set SEED_URL in .env." >&2; exit 1; }
  echo "downloading $URL"; mkdir -p seed; curl -fL --progress-bar -o "$FILE" "$URL"
fi
if [[ -f "$FILE.sha256" ]]; then
  want="$(cut -d' ' -f1 "$FILE.sha256")"; have="$(shasum -a 256 "$FILE" | cut -d' ' -f1)"
  [[ "$want" == "$have" ]] || { echo "checksum mismatch for $FILE (expected $want, got $have)" >&2; exit 1; }
fi
echo "loading $FILE ..."
gunzip -c "$FILE" | psql "$DB" -v ON_ERROR_STOP=1 -q
echo "done: $(psql "$DB" -tAc 'SELECT count(*) FROM papers') papers loaded."
[[ -f seed/MANIFEST.txt ]] && cat seed/MANIFEST.txt || true
[[ "$(psql "$DB" -tAc 'SELECT count(*) FROM embeddings')" == "0" ]] && echo "Next: run 'make index' to build the semantic search index (downloads a ~64 MB model once)." || true
