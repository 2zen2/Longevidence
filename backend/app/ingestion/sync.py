"""Orchestrates a PubMed search -> fetch -> OpenAlex enrich -> idempotent persist, with a sync log."""
import argparse
import logging

from ..config import settings
from ..db import connect, jsonb
from .openalex import OpenAlexClient
from .pubmed import PubMedClient
from .repo import IdentifierConflict, upsert_paper

log = logging.getLogger("longevidence.sync")


def run_sync(question: str, query: str, retmax: int = 30, *, pubmed: PubMedClient | None = None,
             openalex: OpenAlexClient | None = None, use_openalex: bool = True,
             sort: str = "pub_date", on_progress=None) -> int:
    pubmed = pubmed or PubMedClient()
    openalex = openalex or OpenAlexClient()
    counts = {"found_total": 0, "fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0,
              "failed": 0, "no_abstract": 0, "openalex_matched": 0, "openalex_missing": 0}
    errors: list[dict] = []

    with connect() as conn:
        qid = conn.execute(
            "INSERT INTO research_questions (question, query) VALUES (%s,%s) "
            "ON CONFLICT (query) DO UPDATE SET question=EXCLUDED.question RETURNING id", (question, query)
        ).fetchone()["id"]
        run_id = conn.execute(
            "INSERT INTO sync_runs (source, query, question_id, params) VALUES ('pubmed+openalex',%s,%s,%s) RETURNING id",
            (query, qid, jsonb({"retmax": retmax, "use_openalex": use_openalex}))).fetchone()["id"]
        conn.commit()

        def finish(status: str):
            conn.execute("UPDATE sync_runs SET status=%s, finished_at=now(), counts=%s, errors=%s WHERE id=%s",
                         (status, jsonb(counts), jsonb(errors), run_id))
            conn.commit()

        try:
            pmids, total = pubmed.search(query, retmax, sort)
            counts["found_total"] = total
            records = pubmed.fetch(pmids)
        except Exception as e:  # search/fetch failure after retries: nothing persisted
            errors.append({"stage": "pubmed", "error": repr(e)})
            finish("failed")
            raise
        by_pmid = {r.pmid: r for r in records}
        counts["fetched"] = len(records)
        for pm in pmids:
            if pm not in by_pmid:
                counts["failed"] += 1
                errors.append({"pmid": pm, "stage": "parse", "error": "PMID requested but missing in response"})

        for rank, pm in enumerate(pmids, 1):
            if on_progress:
                on_progress(rank - 1, len(pmids))
            rec = by_pmid.get(pm)
            if not rec:
                continue
            if not rec.abstract_text:
                counts["no_abstract"] += 1
            work = None
            if use_openalex:
                try:
                    work = openalex.get_by(rec.pmid, rec.doi)
                    counts["openalex_matched" if work else "openalex_missing"] += 1
                except Exception as e:  # enrichment is optional: record and continue
                    errors.append({"pmid": pm, "stage": "openalex", "error": repr(e)})
            try:
                paper_id, outcome = upsert_paper(conn, rec, work)
                conn.execute(
                    "INSERT INTO question_papers (question_id, paper_id, rank) VALUES (%s,%s,%s) "
                    "ON CONFLICT (question_id, paper_id) DO UPDATE SET rank=EXCLUDED.rank", (qid, paper_id, rank))
                conn.commit()
                counts[outcome] += 1
            except (IdentifierConflict, Exception) as e:
                conn.rollback()
                counts["failed"] += 1
                errors.append({"pmid": pm, "stage": "persist",
                               "error": repr(e), "conflict": isinstance(e, IdentifierConflict)})
        finish("success" if not errors else "partial")
    log.info("sync %s done: %s", run_id, counts)
    return run_id


def load_questions() -> list[dict]:
    import json
    return json.loads((settings.data_dir / "questions.json").read_text())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description="Ingest papers for research questions from data/questions.json")
    ap.add_argument("slugs", nargs="*", help="question slugs (default: all)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--retmax", type=int, help="override per-question paper limit")
    ap.add_argument("--no-openalex", action="store_true")
    a = ap.parse_args()
    qs = load_questions()
    if a.list:
        for q in qs:
            print(f"{q['slug']:10s} {q['question']}")
        raise SystemExit
    unknown = set(a.slugs) - {q["slug"] for q in qs}
    if unknown:
        raise SystemExit(f"unknown question(s): {', '.join(sorted(unknown))}; see --list")
    for q in [q for q in qs if not a.slugs or q["slug"] in a.slugs]:
        rid = run_sync(q["question"], q["query"], a.retmax or q.get("retmax", 30), use_openalex=not a.no_openalex)
        with connect() as c:
            row = c.execute("SELECT status, counts, errors FROM sync_runs WHERE id=%s", (rid,)).fetchone()
        print(f"[{q['slug']}] sync_run {rid}: {row['status']} {row['counts']}")
        for e in row["errors"]:
            print("   error:", e)
