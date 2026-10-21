from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # longevidence/
BACKEND = ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://localhost/longevidence_db"
    ncbi_email: str = "unset@example.com"
    ncbi_api_key: str = ""
    openalex_mailto: str = "unset@example.com"
    llm_provider: str = "anthropic"   # anthropic | openai | openrouter | google
    llm_model: str = ""               # empty -> provider default (see llm.DEFAULT_MODELS)
    llm_api_key: str = ""
    prompt_version: str = "v1"        # v1 | v2 (see extraction/prompts.py)
    llm_mode: str = "replay"          # replay | record | live
    llm_assist: bool = True           # answer-time model help (claim reading, borderline findings); needs LLM_API_KEY, off in tests
    llm_daily_cap: int = 300          # max uncached model calls per day; beyond it the rules-only answer is used
    ingest_max_papers: int = 50       # upper bound on papers per topic-ingestion job
    ingest_workers: int = 4           # parallel LLM calls during topic ingestion
    data_dir: Path = BACKEND / "data"
    cors_origins: str = "http://localhost:3010,http://127.0.0.1:3010"   # comma-separated origins allowed to call the API from a browser; "*" = any (no auth or cookies are used)
    ingest_token: str = ""            # when set, POST /api/ingest/* needs this in the X-Ingest-Token header (the web proxy adds it)

    # The demo research question
    question: str = (
        "Do SGLT2 inhibitors reduce heart-failure hospitalization or cardiovascular death "
        "in adults with heart failure?"
    )
    pubmed_query: str = (
        '(SGLT2 inhibitor*[Title/Abstract] OR dapagliflozin[Title/Abstract] OR empagliflozin[Title/Abstract] '
        'OR canagliflozin[Title/Abstract] OR sotagliflozin[Title/Abstract]) '
        'AND "heart failure"[Title] AND randomized controlled trial[Publication Type] '
        'AND hasabstract[text] AND 2019:2026[dp]'
    )


settings = Settings()
