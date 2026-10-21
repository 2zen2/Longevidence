"""Assemble, audit, cache and return the evidence report for a question."""
import hashlib
import json
import re

from ..db import jsonb
from .audit import audit_statements
from .caveats import build_caveats
from .interpret import alias_topic, from_model_reading, interpret, presets
from .synthesize import (ENGINE_VERSION, DESIGN_LABEL, appraise_paper, build_statements, certainty_for, cluster_outcomes, context_passages,
                         find_conflicts, retrieve_papers, select_tier, verdict_for)

EXCLUDE_TEXT = {
    "not_extracted": "no extraction yet",
    "exposure_only_part_of_combination": "the exposure is only one component of a combination regimen, so the result is not attributable to it",
    "exposure_not_studied": "the question's exposure/intervention is mentioned but is not what the paper studies",
    "only_subgroup_or_prognostic": "its only findings on the outcome are subgroup, interaction or biomarker-association results, not the overall effect",
    "no_finding_on_asked_outcome": "no extracted finding on the outcome the question asks about",
    "relevant_finding_not_verified": "a finding on the outcome exists but its quote/numbers did not verify, so it is not counted",
    "population_out_of_scope": "the study population or setting is outside what the question asks about (e.g. pregnancy, infants, ICU, people already diagnosed with cancer)",
    "study_type_out_of_scope": "a policy, tax or global-burden analysis rather than a study of the exposure's own effect",
    "other_outcome_tier": "its findings are on a different kind of outcome (e.g. a lab marker) than the one the verdict is judged on; listed, not tallied",
}


def _resolve_passages(conn, uids: list[str]) -> dict:
    if not uids:
        return {}
    rows = conn.execute(
        "SELECT p.uid, p.paper_id, p.section, p.section_title, p.kind, p.label, p.text, d.kind AS doc_kind, d.license "
        "FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.uid = ANY(%s)", (uids,)).fetchall()
    return {r["uid"]: {k: r[k] for k in ("paper_id", "section", "section_title", "kind", "label", "text", "doc_kind", "license")} for r in rows}


def build_report(conn, question: str, polarity: str | None = None, refresh: bool = False, deep: bool = False) -> dict:
    """Rules first. If they find fewer than 3 studies, the question is tried as an everyday phrasing of a preset topic ("bacon" -> red meat). The model is asked
    to re-read the claim when the rules look unsure (no exposure found, direction guessed) or are still under 3 studies; any alternative reading is used only
    if it counts more studies. Borderline papers may also be judged by it (see _build)."""
    from . import llm_assist
    interp = interpret(question, polarity)
    if interp.source != "parsed":
        return _build(conn, question, interp, refresh)
    assist = llm_assist.enabled()
    vague_organ = re.search(r"\b(?:for|to|on)\s+(?:the\s+|your\s+)?(?:brain|liver|kidneys?|gut|skin|eyes?|immune|immunity|memory|mood|sleep|digestion|gums?|teeth|hair|joints?|lungs?)\b|\b(?:gut|brain|liver|kidney|skin|eye|immune|joint|mental|digestive|bone) health\b", question.lower())
    unsure = interp.polarity_source == "assumed" or not interp.exposure_words or bool(vague_organ)
    if (unsure or deep) and assist:   # deep: always let the model re-read the claim (the caller asked for it)
        m = llm_assist.read_claim(conn, question)
        if m:
            interp = from_model_reading(question, m, polarity)
    best = _build(conn, question, interp, refresh)
    if best["counts"]["counted"] >= 3 or interp.model_read:
        return best
    topic = alias_topic(question, polarity)
    if topic:
        alt = _build(conn, question, topic, refresh)
        if alt["counts"]["counted"] > best["counts"]["counted"]:
            best = alt
    if best["counts"]["counted"] >= 3 or not assist:
        return best
    m = llm_assist.read_claim(conn, question)
    if m:
        alt = _build(conn, question, from_model_reading(question, m, polarity), refresh)
        if alt["counts"]["counted"] > best["counts"]["counted"]:
            return alt
    return best


def _build(conn, question: str, interp, refresh: bool = False) -> dict:
    from . import llm_assist
    papers = retrieve_papers(conn, interp)
    # cache key: question interpretation + every claim/status/passage the answer can depend on
    ids = sorted(p["id"] for p in papers)   # sorted so a changed row order in the database does not change the cache key
    basis = conn.execute(
        "SELECT c.id, c.extraction_status, (SELECT string_agg(p.uid, ',' ORDER BY p.uid) FROM claim_evidence ce JOIN passages p ON p.id=ce.passage_id WHERE ce.claim_id=c.id) uids "
        "FROM claims c WHERE c.paper_id = ANY(%s) ORDER BY c.id", (ids,)).fetchall() if ids else []
    key = hashlib.sha256(json.dumps([interp.dict(), ids, llm_assist.enabled(), [tuple(b.values()) for b in basis], ENGINE_VERSION], default=str, sort_keys=True).encode()).hexdigest()
    if not refresh:
        hit = conn.execute("SELECT id, report FROM evidence_reports WHERE input_hash=%s AND engine_version=%s", (key, ENGINE_VERSION)).fetchone()
        if hit:
            return {**hit["report"], "report_id": hit["id"], "cached": True}

    top = {p["id"] for p in papers[:8]}
    budget = [4]                                                             # at most 4 borderline papers judged per claim

    def judge(paper, out):
        if interp.source != "parsed" or paper["id"] not in top or budget[0] <= 0 or not llm_assist.enabled():
            return None
        budget[0] -= 1
        return llm_assist.judge_paper(conn, interp, paper, out)

    studies = [appraise_paper(conn, p, interp, judge) for p in papers]
    tiers = select_tier(studies, interp)                  # the verdict is judged on ONE outcome tier; other-tier studies are set aside, visibly
    counted = sorted([s for s in studies if s["counted"]], key=lambda s: -s["weight"])
    by_id = {s["paper_id"]: s for s in studies}
    clusters = cluster_outcomes(studies)
    conflicts = find_conflicts(counted)
    verdict = verdict_for(counted)
    verdict["tier"] = tiers.get("primary")
    verdict["tier_label"] = tiers.get("label")
    certainty = certainty_for(counted, verdict, conflicts, clusters, tiers)
    scope_log = [{"paper_id": s["paper_id"], "title": s["title"], "reason": s["excluded_reason"], "detail": s.get("excluded_detail"),
                  "outcome": s.get("excluded_outcome")} for s in studies
                 if not s["counted"] and s.get("excluded_reason") in ("population_out_of_scope", "study_type_out_of_scope")]
    statements = build_statements(interp, counted, verdict, conflicts, by_id)
    audit = audit_statements(conn, statements)
    ok_ids = {r["id"] for r in audit["results"] if r["ok"]}
    conclusion = [s for s in statements if s["id"] in ok_ids]
    withheld = [s for s in statements if s["id"] not in ok_ids]
    for s in counted:                           # context passages: retrieval only, never counted
        s["context"] = [dict(x) for x in context_passages(conn, s["paper_id"], interp)]

    caveats = build_caveats(conn, counted)
    # resolve every passage the report cites, so the UI can show the verbatim text without further lookups
    uids: set[str] = set()
    for s in studies:
        for f in s.get("findings", []):
            if f["claim_id"] in {x for st in conclusion for x in st["claim_ids"]} or s.get("headline") is f:
                uids |= {e["passage_uid"] for e in f["evidence"]}
        uids |= {sig["passage_uid"] for sig in s.get("signals", []) if sig.get("passage_uid")}
        uids |= {c["uid"] for c in s.get("context", [])}
    uids |= {x["passage_uid"] for x in caveats["safety"]}
    for s in studies:
        for f in s.get("findings", []):
            f.pop("quote_full", None)
    report = {
        "question": question, "interpretation": interp.dict(), "engine_version": ENGINE_VERSION,
        "verdict": verdict, "certainty": certainty,
        "counts": {"retrieved": len(papers), "counted": len(counted),
                   "excluded": {k: sum(1 for s in studies if not s["counted"] and s.get("excluded_reason") == k) for k in EXCLUDE_TEXT}},
        "exclusion_text": EXCLUDE_TEXT, "tiers": tiers, "scope_exclusions": scope_log,
        "studies": [{**s, "design_label": s.get("design_label", DESIGN_LABEL.get(s.get("design", ""), "")),
                     "findings": [f for f in s.get("findings", [])]} for s in sorted(studies, key=lambda s: (not s["counted"], -s.get("weight", 0)))],
        "caveats": caveats, "clusters": clusters, "conflicts": conflicts, "conclusion": conclusion, "withheld": withheld, "audit": audit,
        "passages": _resolve_passages(conn, sorted(uids)),
    }
    row = conn.execute("INSERT INTO evidence_reports (question, interpretation, report, input_hash, engine_version) VALUES (%s,%s,%s,%s,%s) "
                       "ON CONFLICT (input_hash, engine_version) DO UPDATE SET report=EXCLUDED.report, created_at=now() RETURNING id",
                       (question, jsonb(interp.dict()), jsonb(report), key, ENGINE_VERSION)).fetchone()
    conn.execute("DELETE FROM evidence_reports WHERE id IN (SELECT id FROM evidence_reports WHERE NOT (question = ANY(%s)) "
                 "ORDER BY created_at DESC OFFSET 300)", ([p["question"] for p in presets()],))   # bounded history of free-text reports; the preset questions' reports are never evicted
    conn.commit()
    return {**report, "report_id": row["id"], "cached": False}


if __name__ == "__main__":
    import sys
    from ..db import connect
    q = " ".join(sys.argv[1:]) or "Do SGLT2 inhibitors reduce heart-failure hospitalization or cardiovascular death in adults with heart failure?"
    with connect() as c:
        r = build_report(c, q, refresh=True)
    print(json.dumps({k: r[k] for k in ("interpretation", "verdict", "certainty", "counts", "audit")}, indent=1, default=str)[:4000])
    for s in r["conclusion"][:6]:
        print("-", s["text"])
