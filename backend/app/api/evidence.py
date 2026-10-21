"""Endpoints for a paper's stored document and for question -> evidence report."""
from fastapi import APIRouter, HTTPException, Query

from ..db import connect
from ..synthesis.report import build_report

router = APIRouter(prefix="/api")


@router.get("/papers/{paper_id}/document", tags=["Corpus"], summary="Stored passages and claims for a paper")
def paper_document(paper_id: int):
    """Stored documents, their passages (with section structure), and the claims linked to those passages."""
    with connect() as c:
        if not c.execute("SELECT 1 FROM papers WHERE id=%s", (paper_id,)).fetchone():
            raise HTTPException(404, "paper not found")
        docs = c.execute("SELECT id, kind, source_url, license, raw_sha256, text_hash, parser_version, printed_pages, fetched_at, "
                         "length(text) AS chars FROM documents WHERE paper_id=%s ORDER BY kind DESC", (paper_id,)).fetchall()
        passages = c.execute(
            "SELECT p.id, p.uid, p.document_id, p.ordinal, p.section, p.section_title, p.kind, p.label, p.page_number, p.printed_page, "
            "p.text, p.start_offset, p.end_offset, p.table_json FROM passages p WHERE p.paper_id=%s ORDER BY p.document_id, p.ordinal", (paper_id,)).fetchall()
        claims = c.execute(
            "SELECT c.id, c.claim_key, c.claim_type, c.text, c.structured, c.extraction_status, c.status_reasons, c.extraction_run_id, c.ft_run_id, "
            "coalesce(e.model_name, f.model_name) AS model_name, coalesce(e.prompt_version, f.prompt_version) AS prompt_version "
            "FROM claims c LEFT JOIN extraction_runs e ON e.id=c.extraction_run_id LEFT JOIN fulltext_runs f ON f.id=c.ft_run_id "
            "WHERE c.paper_id=%s AND (c.extraction_run_id=(SELECT extraction_run_id FROM claims WHERE paper_id=%s AND extraction_run_id IS NOT NULL ORDER BY id DESC LIMIT 1) "
            "OR c.ft_run_id=(SELECT ft_run_id FROM claims WHERE paper_id=%s AND ft_run_id IS NOT NULL ORDER BY id DESC LIMIT 1)) "
            "ORDER BY (c.ft_run_id IS NOT NULL), c.id", (paper_id, paper_id, paper_id)).fetchall()
        links = c.execute(
            "SELECT ce.claim_id, ce.evidence_role, ce.origin, ce.quote_start, ce.quote_end, ce.verification, ce.extraction_status, p.uid AS passage_uid "
            "FROM claim_evidence ce JOIN passages p ON p.id=ce.passage_id JOIN claims c ON c.id=ce.claim_id WHERE p.paper_id=%s", (paper_id,)).fetchall()
        attempt = c.execute("SELECT status, detail, attempted_at FROM fulltext_attempts WHERE paper_id=%s AND source='europepmc'", (paper_id,)).fetchone()
    by_claim: dict[int, list] = {}
    for l in links:
        by_claim.setdefault(l["claim_id"], []).append(l)
    for cl in claims:
        cl["evidence"] = by_claim.get(cl["id"], [])
    kind_of = {d["id"]: d["kind"] for d in docs}
    for p in passages:
        p["doc_kind"] = kind_of[p["document_id"]]
    return {"documents": docs, "passages": passages, "claims": claims, "fulltext_attempt": attempt}


@router.get("/ask", tags=["Evidence"], summary="Answer a question with an evidence report")
def ask(q: str = Query(..., min_length=8, max_length=400, description="A plain-language question.", examples=["Does NMN actually raise NAD+ levels?"]),
        polarity: str | None = Query(None, pattern="^(benefit|harm)$", description="Override the detected direction: is the question about a benefit or a harm?"),
        refresh: bool = Query(False, description="Ignore the cached report and recompute."),
        deep: bool = Query(False, description="Have the connected language model re-read the question (ignored when none is configured).")):
    """Verdict, certainty, the counted and set-aside studies, caveats and the quote-level citations behind every statement. Reports are cached by input hash."""
    with connect() as c:
        return build_report(c, q, polarity, refresh, deep)


@router.get("/assist/status", tags=["Evidence"], summary="Can the model help read free-text questions?")
def assist_status():
    from ..config import settings
    from ..extraction.llm import llm_status
    st = llm_status()
    return {"enabled": bool(st["ready"] and settings.llm_assist), "provider": st["provider"], "model": st["model"]}
