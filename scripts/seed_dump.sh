#!/usr/bin/env bash
# Export the current database to seed/data.sql.gz plus a checksum and a short manifest.
# Excluded to keep the file small enough to email: cached evidence reports (rebuild on demand) and search embeddings (rebuild with `make index`).
set -euo pipefail
cd "$(dirname "$0")/.."
DB="${DATABASE_URL:-$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)}"
mkdir -p seed
pg_dump --no-owner --no-privileges --data-only --exclude-table-data=evidence_reports --exclude-table-data=embeddings "$DB" \
  | grep -vE '^(SET transaction_timeout|\\restrict |\\unrestrict )' | gzip -9 > seed/data.sql.gz   # newer pg_dump emits lines that PostgreSQL 15/16 and older psql reject
shasum -a 256 seed/data.sql.gz | sed 's#  .*#  data.sql.gz#' > seed/data.sql.gz.sha256
{
  echo "Seed data exported $(date -u +%Y-%m-%d)"
  psql "$DB" -tAc "SELECT 'papers: '||count(*) FROM papers"
  psql "$DB" -tAc "SELECT 'claims: '||count(*) FROM claims"
  echo "embeddings: not included (run 'make index' after loading)"
} > seed/MANIFEST.txt
ls -lh seed/data.sql.gz | awk '{print "wrote seed/data.sql.gz (" $5 ")"}'
