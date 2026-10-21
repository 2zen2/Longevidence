"""Topic ingestion jobs: search PubMed/OpenAlex -> store -> extract -> claims -> embed, with progress in the `ingest_jobs` table.

One job at a time (each one spends model budget and NCBI rate limit). A job runs in a background thread of the API process;
rows left 'running' by a crashed/restarted server are marked failed at start-up. Everything is idempotent, so re-running the same
topic reuses stored papers, cached extractions and existing embeddings."""
import logging
import threading

from ..claims.materialize import materialize_fulltext, materialize_paper
from ..config import settings
from ..db import connect, jsonb
from ..documents.build import build_abstracts, build_fulltext
from ..extraction.llm import LLMClient, LLMFatalError, ingest_client
from ..extraction.runner import extract_all
from ..search.build import build as build_embeddings
from .openalex import OpenAlexClient
from .pubmed import PubMedClient
from .sync import run_sync

log = logging.getLogger("longevidence.ingest")
ACTIVE = ("queued", "running")


class JobBusy(Exception):
    """Another ingestion job is still queued or running."""


def create_job(topic: str, query: str, retmax: int, fulltext: bool = False) -> int:
    retmax = max(1, min(retmax, settings.ingest_max_papers))
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(727001)")       # serialise the busy check against concurrent requests
        if conn.execute("SELECT 1 FROM ingest_jobs WHERE status = ANY(%s)", (list(ACTIVE),)).fetchone():
            raise JobBusy("an ingestion job is already running")
        jid = conn.execute("INSERT INTO ingest_jobs (topic, query, params) VALUES (%s,%s,%s) RETURNING id",
                           (topic, query, jsonb({"retmax": retmax, "fulltext": fulltext}))).fetchone()["id"]
        conn.commit()
    return jid


def start_job(job_id: int) -> threading.Thread:
    t = threading.Thread(target=run_job, args=(job_id,), name=f"ingest-{job_id}", daemon=True)
    t.start()
    return t


def recover_orphans() -> int:
    with connect() as conn:
        n = conn.execute("UPDATE ingest_jobs SET status='failed', error='interrupted by a server restart', finished_at=now() "
                         "WHERE status = ANY(%s)", (list(ACTIVE),)).rowcount
        conn.commit()
    return n


def _update(job_id: int, **cols) -> None:
    sets, vals = [], []
    for k, v in cols.items():
        sets.append(f"{k}=%s")
        vals.append(jsonb(v) if k in ("counts", "warnings") else v)
    with connect() as conn:
        conn.execute(f"UPDATE ingest_jobs SET {', '.join(sets)} WHERE id=%s", (*vals, job_id))
        conn.commit()


def run_job(job_id: int, client: LLMClient | None = None, pubmed: PubMedClient | None = None,
            openalex: OpenAlexClient | None = None) -> None:
    with connect() as conn:
        job = conn.execute("SELECT topic, query, params FROM ingest_jobs WHERE id=%s", (job_id,)).fetchone()
    retmax, fulltext = job["params"]["retmax"], job["params"].get("fulltext", False)
    counts: dict = {}
    warnings: list[str] = []
    fatal: str | None = None
    _update(job_id, status="running", stage="search")
    try:
        client = client or ingest_client()
        # PubMed relevance order (not newest-first): a topic query should bring the best matches, not just the latest.
        run_id = run_sync(job["topic"], job["query"], retmax, pubmed=pubmed, openalex=openalex, sort="relevance",
                          on_progress=lambda d, t: _update(job_id, stage="search", done=d, total=t))
        with connect() as conn:
            sr = conn.execute("SELECT status, counts, question_id, errors FROM sync_runs WHERE id=%s", (run_id,)).fetchone()
            ids = [r["paper_id"] for r in conn.execute(
                "SELECT paper_id FROM question_papers WHERE question_id=%s AND rank<=%s ORDER BY rank", (sr["question_id"], retmax))]
        counts.update(found_total=sr["counts"].get("found_total", 0), papers=len(ids), inserted=sr["counts"].get("inserted", 0),
                      no_abstract=sr["counts"].get("no_abstract", 0))
        if sr["errors"]:
            warnings.append(f"{len(sr['errors'])} record(s) had search/persist problems (see sync run {run_id})")
        _update(job_id, question_id=sr["question_id"], paper_ids=ids, counts=counts, warnings=warnings)

        _update(job_id, stage="documents", done=0, total=len(ids))
        with connect() as conn:
            build_abstracts(conn, ids)

        _update(job_id, stage="extract", done=0, total=len(ids))
        try:
            counts["extraction"] = extract_all(client, workers=settings.ingest_workers, only=set(ids),
                                               on_progress=lambda d, t: _update(job_id, stage="extract", done=d, total=t))
        except LLMFatalError as e:         # key/quota problem: keep what was extracted so far and finish the remaining stages on it
            fatal = f"model call refused: {e}"
        _update(job_id, counts=counts)

        if fulltext and not fatal:
            _update(job_id, stage="fulltext", done=0, total=0)
            from ..extraction.fulltext import run_all as extract_fulltext
            with connect() as conn:
                counts["fulltext_documents"] = build_fulltext(conn, ids)
            try:
                counts["fulltext_extraction"] = extract_fulltext(client, workers=settings.ingest_workers, only=ids)
            except LLMFatalError as e:
                fatal = f"model call refused during full-text extraction: {e}"
            _update(job_id, counts=counts)

        _update(job_id, stage="claims", done=0, total=len(ids))
        n_claims = 0
        with connect() as conn:
            for i, pid in enumerate(ids, 1):
                n_claims += materialize_paper(conn, pid).get("claims", 0) + materialize_fulltext(conn, pid).get("claims", 0)
                conn.commit()
        counts["claims"] = n_claims
        _update(job_id, done=len(ids), counts=counts)

        _update(job_id, stage="embed", done=0, total=0)
        try:
            counts["embeddings"] = build_embeddings(ids)
        except Exception as e:             # papers and claims are stored and keyword search works; semantic search just lacks these
            log.exception("embedding failed for job %s", job_id)
            warnings.append(f"semantic index not built for these papers: {e!r}")
        _update(job_id, counts=counts, warnings=warnings)
    except Exception as e:
        log.exception("ingest job %s failed", job_id)
        _update(job_id, status="failed", error=f"{type(e).__name__} (details in the server log)", counts=counts, warnings=warnings)
        _finish(job_id)
        return
    if fatal:
        _update(job_id, status="failed", error=fatal[:500])
    else:
        _update(job_id, status="done", stage="done")
    _finish(job_id)


def _finish(job_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE ingest_jobs SET finished_at=now() WHERE id=%s", (job_id,))
        conn.commit()


def job_view(job_id: int) -> dict | None:
    with connect() as conn:
        j = conn.execute("SELECT id, topic, query, params, status, stage, done, total, counts, warnings, error, question_id, paper_ids, "
                         "created_at, finished_at FROM ingest_jobs WHERE id=%s", (job_id,)).fetchone()
        if not j:
            return None
        papers = conn.execute(
            "SELECT p.id, p.title, p.journal, extract(year from p.publication_date)::int AS year, "
            "EXISTS (SELECT 1 FROM extraction_runs e WHERE e.paper_id=p.id AND e.status='ok') AS extracted, "
            "(SELECT count(*) FROM claims c WHERE c.paper_id=p.id) AS claims "
            "FROM papers p WHERE p.id = ANY(%s) ORDER BY array_position(%s::bigint[], p.id)", (j["paper_ids"], j["paper_ids"])).fetchall()
    j["papers"] = papers
    j["n_papers"] = len(j.pop("paper_ids"))
    return j
