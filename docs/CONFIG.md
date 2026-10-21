# Configuration reference

Settings are read from environment variables or `.env` in the repo root (see `backend/app/config.py`). Only `DATABASE_URL` is needed to run the app.

## Everyday

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://localhost/longevidence_db` | Postgres connection string. `.env.example` uses the Docker credentials from `docker-compose.yml` |
| `SEED_URL` | empty | Where `make seed` downloads the example data from if `seed/data.sql.gz` is missing |
| `CORS_ORIGINS` | `http://localhost:3010,http://127.0.0.1:3010` | Comma-separated browser origins allowed to call the API. `*` lets any site call it; the API has no cookies |
| `INGEST_TOKEN` | empty | When set, `POST /api/ingest/plan` and `POST /api/ingest` require it in an `X-Ingest-Token` header. The web app reads the same variable and sends it from its server |

## Model help (optional)

Used at answer time to read unusual questions and judge borderline papers. Results are cached in the database and capped per day. Without a key, cached readings still replay and everything else uses the rules.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, `openrouter` or `google` (Gemini). Used for answer-time help, extraction and topic ingestion |
| `LLM_MODEL` | provider default | Model name. Defaults: `claude-sonnet-5-5`, `gpt-5-nano-2025-08-07`, `deepseek/deepseek-chat` (OpenRouter), `gemini-2.5-flash` |
| `LLM_API_KEY` | empty | API key for the chosen provider (the only key variable) |
| `LLM_ASSIST` | `true` | Set `false` to turn answer-time model help off entirely |
| `LLM_DAILY_CAP` | `300` | Maximum uncached model calls per day |

## Fetching new papers

| Variable | Default | Purpose |
|---|---|---|
| `NCBI_EMAIL` | placeholder | Contact email sent with every PubMed request (NCBI asks for one) |
| `NCBI_API_KEY` | empty | Optional; raises the PubMed rate limit from 3 to 10 requests/s |
| `OPENALEX_MAILTO` | placeholder | Contact email for OpenAlex |

## Extraction internals (rarely needed)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_MODE` | `replay` | `replay` uses only recorded responses, `record` calls the API and saves, `live` calls without saving |
| `PROMPT_VERSION` | `v1` | Extraction prompt: `v1` (frozen) or `v2` (skeleton with required quotes, for models that ignore the tool schema) |
