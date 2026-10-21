"""Ingest new papers for a topic. Offered only when a model is configured (GET /api/ingest/status says whether).

    POST /api/ingest/plan  {topic}                  -> the PubMed query the model proposes + how many records it matches (nothing is stored)
    POST /api/ingest       {topic, query, retmax}   -> starts a background job (202), one at a time
    GET  /api/ingest/{id}                           -> progress, counts and the papers found"""
import hmac
import logging
import time
from collections import deque

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..db import connect
from ..extraction.llm import LLMFatalError, ingest_client, llm_status
from ..ingestion import jobs
from ..ingestion.topic import plan_query, valid_query

log = logging.getLogger(__name__)
_posts: deque[float] = deque()      # recent POST times; ingestion spends model budget, so cap how often it can be started
MAX_POSTS, WINDOW_S = 20, 600


def guard(x_ingest_token: str | None = Header(None)):
    if settings.ingest_token and not hmac.compare_digest(x_ingest_token or "", settings.ingest_token):
        raise HTTPException(401, "ingestion needs a valid X-Ingest-Token")
    now = time.monotonic()
    while _posts and now - _posts[0] > WINDOW_S:
        _posts.popleft()
    if len(_posts) >= MAX_POSTS:
        raise HTTPException(429, "too many ingestion requests; try again in a few minutes")
    _posts.append(now)


router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])


class PlanIn(BaseModel):
    topic: str = Field(min_length=3, max_length=200, examples=["Avocados and cardiovascular diseases"])


class IngestIn(PlanIn):
    query: str = Field(min_length=3, max_length=800, description="PubMed query, normally the one returned by /plan (possibly edited).")
    retmax: int = Field(30, ge=1, description="How many papers to ingest (capped by INGEST_MAX_PAPERS).")
    fulltext: bool = Field(False, description="Also fetch open-access full text from Europe PMC and extract from it (slower, more model calls).")


def _require_llm() -> dict:
    st = llm_status()
    if not st["ready"]:
        raise HTTPException(503, f"Ingestion needs a connected language model: {st['reason']}")
    return st


@router.get("/status", summary="Is topic ingestion available?")
def status():
    st = llm_status()
    try:
        with connect() as c:
            active = c.execute("SELECT id FROM ingest_jobs WHERE status = ANY(%s) ORDER BY id DESC LIMIT 1", (list(jobs.ACTIVE),)).fetchone()
    except psycopg.errors.UndefinedTable:        # schema not migrated yet (`make migrate`): ingestion cannot run, say so instead of failing
        return {"enabled": False, "provider": st["provider"], "model": st["model"], "reason": "database needs `make migrate`",
                "max_papers": settings.ingest_max_papers, "active_job": None}
    return {"enabled": st["ready"], "provider": st["provider"], "model": st["model"], "reason": st["reason"],
            "max_papers": settings.ingest_max_papers, "active_job": active["id"] if active else None}


@router.post("/plan", summary="Propose a PubMed query for a topic (stores nothing)", dependencies=[Depends(guard)])
def plan(body: PlanIn):
    _require_llm()
    try:
        return plan_query(body.topic, ingest_client())
    except LLMFatalError:
        log.exception("model refused the plan request")
        raise HTTPException(502, "The model refused the request.")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception:
        log.exception("plan_query failed")
        raise HTTPException(502, "Could not reach PubMed or the model.")


@router.post("", status_code=202, summary="Start ingesting papers for a topic", dependencies=[Depends(guard)])
def start(body: IngestIn):
    _require_llm()
    if not valid_query(body.query):
        raise HTTPException(422, "query is not a well-formed PubMed query (check parentheses and quotes)")
    try:
        job_id = jobs.create_job(" ".join(body.topic.split()), " ".join(body.query.split()), body.retmax, body.fulltext)
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))
    jobs.start_job(job_id)
    return {"job_id": job_id}


@router.get("", summary="Recent ingestion jobs")
def recent(limit: int = 10):
    with connect() as c:
        return c.execute("SELECT id, topic, status, stage, created_at, finished_at, cardinality(paper_ids) AS n_papers FROM ingest_jobs "
                         "ORDER BY id DESC LIMIT %s", (min(max(limit, 1), 50),)).fetchall()


@router.get("/{job_id}", summary="Progress and result of one ingestion job")
def job(job_id: int):
    j = jobs.job_view(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j
