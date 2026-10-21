# Longevidence - common tasks. Run `make help`.
PY := backend/.venv/bin/python
API_PORT ?= 8010
WEB_PORT ?= 3010

help:        ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ -/'

setup:       ## install backend + frontend dependencies
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

up:          ## start Postgres (docker). Skip if you use a local Postgres and set DATABASE_URL
	docker compose up -d --wait

quickstart:  ## one command: install, database, example data, embedding model, then run API + web
	scripts/quickstart.sh

seed:        ## load the example dataset into an empty database (downloads it from SEED_URL if seed/data.sql.gz is missing); safe to re-run
	scripts/seed.sh

seed-dump:   ## export the current database to seed/data.sql.gz (+ checksum and manifest) for sharing
	scripts/seed_dump.sh

migrate:     ## create/upgrade the schema (idempotent)
	cd backend && .venv/bin/python -m app.db

ingest:      ## PubMed + OpenAlex for all questions in data/questions.json (or: make ingest Q="vitd fasting"). Safe to re-run
	cd backend && .venv/bin/python -m app.ingestion.sync $(Q)

extract:     ## LLM extraction for every ingested paper (needs LLM_API_KEY, LLM_MODE=record|live)
	cd backend && LLM_MODE=$${LLM_MODE:-record} .venv/bin/python -m app.extraction.runner --workers $(W)

documents:   ## B: stored documents + passages for every paper (abstracts; make documents FULLTEXT=1 also fetches Europe PMC open-access full text)
	cd backend && .venv/bin/python -m app.documents.build $(if $(FULLTEXT),--fulltext)

claims:      ## B: turn extraction runs into claim records linked to stored passages (idempotent; rerun after `make extract`)
	cd backend && .venv/bin/python -m app.claims.materialize

extract-ft:  ## B: LLM extraction from full-text passages with passage-level citations (make extract-ft W=4; resumes from cache; then `make claims`)
	cd backend && LLM_MODE=$${LLM_MODE:-record} .venv/bin/python -m app.extraction.fulltext --workers $(W)

ask:         ## C: evidence report from the CLI (make ask Q="Does vitamin D reduce fractures?"); `make ask` runs the SGLT2 demo question
	cd backend && .venv/bin/python -m app.synthesis.report $(Q)

index:        ## search: embed papers + passages with bge-small (downloads ~64 MB once; resumable); BM25 and metadata indexes are built in memory at start-up
	cd backend && .venv/bin/python -m app.search.build



W ?= 1




test:        ## unit + integration tests (offline; needs Postgres for db tests)
	cd backend && .venv/bin/python -m pytest -q

api:         ## FastAPI on :$(API_PORT)
	cd backend && .venv/bin/uvicorn app.main:app --port $(API_PORT) --reload

demo:        ## serve temporarily through a Cloudflare quick tunnel (needs cloudflared); `make demo-local` to test without it
	scripts/demo.sh

demo-local:  ## same servers as `make demo` on 127.0.0.1:3011, no tunnel
	scripts/demo.sh --no-tunnel

web:         ## Next.js on :$(WEB_PORT)
	cd frontend && npm run dev

.PHONY: index quickstart seed seed-dump documents claims extract-ft ask demo demo-local help setup up migrate ingest extract test api web
