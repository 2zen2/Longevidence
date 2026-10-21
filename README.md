# Longevidence

Ask a plain-language health or longevity question and get an evidence-graded answer: a verdict, a certainty rating, the studies behind it, caveats, and links to the sources. Every claim in an answer links to a quote in a stored source passage.

- **Backend:** FastAPI + PostgreSQL (Python 3.11+)
- **Frontend:** Next.js (Node 20+)

The web app is a patient-facing demo: sign in as one of two fictional profiles (`frontend/src/data/mock_users.json`), simulate device connections, search a topic or type any question (free-form questions are answered from the stored papers), and read the evidence next to a mock personalization. Paper titles open a page with the stored abstract or text and our per-claim evaluation. Personalization text lives in `frontend/src/data/personalization.ts` and is hand-written; everything else comes from the corpus. The earlier researcher UI was removed; the ingestion API is unchanged and is offered from the free-form answer page (see below).

For how the pieces fit together, see [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## Requirements

- Python 3.11+
- Node 20+
- PostgreSQL 16 (or Docker) and the `psql` client

## Quick start

1. **Put the seed data in the `seed/` folder.** Get `data.sql.gz` (and `data.sql.gz.sha256`) from the project owner and place both in `seed/`. They are not stored in git. See [Example data](#example-data) for the alternative of setting `SEED_URL`.
2. **Run the quickstart:**

```bash
make quickstart
```

It creates `.env` if missing, installs dependencies, starts Postgres with Docker if it cannot reach one, applies the schema, loads the seed data, and starts the API and web app. It also builds the semantic search index in the background (the first run downloads a ~64 MB model, so it needs internet; paper-level vectors take about 2 minutes, passage vectors tens of minutes more; set `SKIP_INDEX=1` to skip it). The app is usable meanwhile, with keyword search until vectors exist. Open http://localhost:3010, sign in as one of the two sample profiles and search. It is safe to re-run.

3. **If you skipped the index or stopped quickstart before it finished,** run `make index`. Until then search uses keywords only. It can be stopped and resumed. (pgvector is not needed; embeddings are stored in plain Postgres.)

### Step by step

```bash
cp .env.example .env        # set DATABASE_URL (and NCBI_EMAIL if you will ingest papers)
make setup                  # backend virtualenv + frontend dependencies
make up                     # start Postgres with Docker (skip if you run your own)
make migrate                # create the schema
make seed                   # load the example dataset (skipped if the database already has data)
make api                    # terminal 1: API on http://localhost:8010
make web                    # terminal 2: web app on http://localhost:3010
```

The API documents itself: interactive Swagger UI at http://localhost:8010/docs (try `/api/ask`), ReDoc at `/redoc`, and the machine-readable contract at `/openapi.json` (use it to generate a typed client for your own frontend).

If you use a local Postgres instead of Docker, create the database first and point `DATABASE_URL` at it:

```bash
createdb longevidence_db
# .env: DATABASE_URL=postgresql://localhost/longevidence_db
```

### Example data

`make seed` loads `seed/data.sql.gz` (about 11 MB, 559 papers; it does not include embeddings, which you build locally with `make index`). **It is gitignored, so a fresh clone does not have it, and `make quickstart` stops at the seed step without it.** Get the file from the project owner and put it in `seed/` (keep `data.sql.gz.sha256` next to it), or set `SEED_URL` in `.env` to where it is hosted (for example a release download) and `make seed` fetches and checksum-verifies it. To share your own data, run `make seed-dump`; it writes the file, a checksum and a manifest into `seed/`.

### Adding papers on a new topic (needs a model)

With `LLM_API_KEY` (and `LLM_PROVIDER` / `LLM_MODEL`) set and the schema migrated (`make migrate`), a free-form answer page (`/ask`) offers two extras, and neither appears without a model: **Interpret with AI** (the model re-reads the question to find the right studies) and, when the corpus holds little on the question, **Research this topic**.
It shows the PubMed query the model proposes, you confirm it, then the PubMed query the model proposes (and edit it if needed), then a background job finds up to `INGEST_MAX_PAPERS` (default 50) papers, stores them, extracts the evidence, links claims to source passages and builds the search index, showing progress as it goes. One job runs at a time and roughly one model call is made per paper. API: `GET /api/ingest/status`, `POST /api/ingest/plan`, `POST /api/ingest`, `GET /api/ingest/{id}`. Set `INGEST_TOKEN` to require a token on the ingest POST routes, and `INGEST_UI=off` on the web app to hide the feature and disable its proxy (the tunnel demo, `make demo`, does this).

## Configuration

Only `DATABASE_URL` is needed, and the value in `.env.example` works with the bundled Docker database. Everything else is optional: model help for unusual questions (`LLM_*`), fetching new papers (`NCBI_EMAIL`), and where to download the example data (`SEED_URL`). See [docs/CONFIG.md](docs/CONFIG.md) for every setting.

## Useful commands

```bash
make help        # list all commands
make seed-dump   # export the current database as a shareable example dataset
make test        # run the test suite
make ingest      # fetch papers from PubMed for the questions in backend/data/questions.json
make documents   # build stored passages (add FULLTEXT=1 for open-access full text)
make index       # build semantic search embeddings (downloads the embedding model on first run)
make demo-local  # production build served locally on :3011
```
