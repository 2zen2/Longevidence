from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager

from .api.evidence import router as evidence_router
from .api.ingest import router as ingest_router
from .api.routes import router
from .api.search import router as search_router
from .config import settings

TAGS = [
    {"name": "Evidence", "description": "Ask a question, get a verdict with certainty, caveats and cited quotes. Try `/api/ask` first."},
    {"name": "Corpus", "description": "Browse and search the stored papers, passages and claims behind the answers."},
    {"name": "Ingestion", "description": "Add papers for a new topic (needs a connected language model)."},
    {"name": "System", "description": "Health check."},
]
@asynccontextmanager
async def lifespan(_):
    try:
        from .ingestion.jobs import recover_orphans
        recover_orphans()         # jobs a previous server process left running can never finish
    except Exception:             # database not migrated yet: the API still serves everything else
        pass
    yield


app = FastAPI(lifespan=lifespan, title="Longevidence API", version="0.1.0", openapi_tags=TAGS,
              description="Evidence-graded, source-backed answers to plain-language health questions. Every statement links to a verbatim quote in a stored source passage.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(search_router)
app.include_router(evidence_router)
app.include_router(ingest_router)


@app.get("/api/health", tags=["System"], summary="Liveness check")
def health():
    return {"ok": True}
