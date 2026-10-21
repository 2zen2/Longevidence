"""Turn a stored extraction run into claim records linked to passages.

An LLM output is a *claim*. A claim becomes evidence only when it is tied to a stored passage:
  * extractor_quote: the quote the model gave, located by the verifier (exact/fuzzy) -> passage + offsets inside it
  * numeric_match:   independent corroboration found by code, not by the model - the same effect estimate and interval
                     appear together in one sentence/table row of the full text

Claim status (rule-based; 'verified' means "the cited text exists and contains the numbers", NOT "the claim is correct"):
  verified      exact quote, numbers present, sanity checks pass
  needs_review  approximate quote, a number missing from the quote, or an implausible interval/p-value
  unsupported   no quote, or quote not found in the source
"""
import logging
import re

from ..db import connect, jsonb
from ..extraction.verify import numbers_in

log = logging.getLogger("claims")

STUDY_FIELDS = ("design", "sample_size", "population", "intervention", "comparator", "follow_up")
SOFT_NOTES = ("section_mismatch", "passage_corrected")           # cosmetic, does not lower status


def claim_status(verification: str, notes: list[str]) -> tuple[str, list[str]]:
    reasons = [n for n in (notes or []) if not n.startswith(SOFT_NOTES)]
    if verification in ("failed", "unchecked") or "missing_quote" in reasons or "quote_not_in_source" in reasons:
        reasons = reasons or ["no_verified_quote"]
        if verification == "failed" and any(r.startswith("number_not_in_quote") for r in reasons) and "quote_not_in_source" not in reasons \
                and "missing_quote" not in reasons:
            return "needs_review", reasons
        return "unsupported", reasons
    if verification == "fuzzy":
        return "needs_review", ["approximate_quote"] + reasons
    if reasons:
        return "needs_review", reasons
    return "verified", []


def fmt_finding(f: dict) -> str:
    bits = []
    if f.get("effect_value") is not None:
        bits.append(f"{f.get('effect_measure') or 'effect'} {f['effect_value']:g}")
    if f.get("ci_low") is not None and f.get("ci_high") is not None:
        bits.append(f"(95% CI {f['ci_low']:g} to {f['ci_high']:g})")
    if f.get("p_value") is not None:
        bits.append(f"p = {f['p_value']:g}")
    est = " ".join(bits)
    return f"{f.get('outcome', 'outcome')}: {est + '; ' if est else ''}{str(f.get('direction', '')).replace('_', ' ')}"


def _claims_from_output(ex: dict) -> list[dict]:
    out = []
    for name in STUDY_FIELDS:
        f = (ex.get("study") or {}).get(name) or {}
        if f.get("status") != "reported" or f.get("value") in (None, ""):
            continue
        out.append({"key": f"study.{name}", "type": name, "text": f"{name.replace('_', ' ').capitalize()}: {f['value']}",
                    "structured": {"value": f["value"]}, "loc": f})
    for i, f in enumerate(ex.get("primary_findings") or []):
        s = {k: f.get(k) for k in ("outcome", "direction", "effect_measure", "effect_value", "ci_low", "ci_high", "p_value")}
        out.append({"key": f"finding.{i}", "type": "finding", "text": fmt_finding(f), "structured": s, "loc": f})
    for i, f in enumerate(ex.get("limitations_stated") or []):
        if f.get("status") == "reported" and f.get("value"):
            out.append({"key": f"limitation.{i}", "type": "limitation", "text": f"Stated limitation: {f['value']}",
                        "structured": {"value": f["value"]}, "loc": f})
    return out


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])|\n")     # not on ";": stats like "(HR 0.74, 95% CI 0.6-0.9; P<0.001)" stay together


def _segments(text: str):
    pos = 0
    for part in _SENT.split(text):
        i = text.find(part, pos)
        if i < 0:
            continue
        pos = i + len(part)
        if part.strip():
            yield i, i + len(part), part


def _has(v: float, nums: list[float]) -> bool:
    return any(abs(abs(v) - abs(n)) < 1e-9 for n in nums)


def numeric_matches(structured: dict, passages: list[dict]) -> list[tuple[dict, int, int]]:
    """Passages where the effect estimate AND at least one more reported number (CI bound / p) co-occur in a single segment."""
    ev = structured.get("effect_value")
    if ev is None:
        return []
    need_more = [structured.get(k) for k in ("ci_low", "ci_high", "p_value") if structured.get(k) is not None]
    if not need_more:
        return []
    hits = []
    for p in passages:
        if p["kind"] == "abstract_section":
            continue
        for a, b, seg in _segments(p["text"]):
            nums = numbers_in(seg)
            if _has(ev, nums) and all(_has(v, nums) for v in need_more if v is not None and v != 0):
                hits.append((p, a, b))
                break
    return hits


def materialize_paper(conn, paper_id: int) -> dict:
    run = conn.execute("SELECT id, output FROM extraction_runs WHERE paper_id=%s AND status='ok' ORDER BY created_at DESC LIMIT 1",
                       (paper_id,)).fetchone()
    if not run or not (run["output"] or {}).get("extraction"):
        return {"claims": 0}
    ex = run["output"]["extraction"]
    docs = {d["kind"]: d for d in conn.execute("SELECT id, kind, text FROM documents WHERE paper_id=%s", (paper_id,))}
    abs_doc = docs.get("pubmed_abstract")
    if not abs_doc:
        return {"claims": 0, "skipped": "no abstract document"}
    passages = conn.execute("SELECT id, document_id, uid, kind, text, start_offset, end_offset FROM passages WHERE paper_id=%s ORDER BY id",
                            (paper_id,)).fetchall()
    abs_passages = [p for p in passages if p["document_id"] == abs_doc["id"]]
    full_passages = [p for p in passages if p["document_id"] != abs_doc["id"]]

    conn.execute("DELETE FROM claims WHERE paper_id=%s AND extraction_run_id=%s", (paper_id, run["id"]))
    stats = {"claims": 0, "verified": 0, "needs_review": 0, "unsupported": 0, "numeric_links": 0}
    for c in _claims_from_output(ex):
        loc = c["loc"]
        status, reasons = claim_status(loc.get("verification", "unchecked"), loc.get("notes") or [])
        links = []
        cs, ce = loc.get("char_start"), loc.get("char_end")
        if cs is not None and ce is not None and loc.get("verification") in ("exact", "fuzzy"):
            for p in abs_passages:
                lo, hi = max(cs, p["start_offset"]), min(ce, p["end_offset"])
                if lo < hi:
                    links.append((p, lo - p["start_offset"], hi - p["start_offset"], "extractor_quote", loc["verification"],
                                  "verified" if status == "verified" else "needs_review"))
        if c["type"] == "finding":
            for p, a, b in numeric_matches(c["structured"], full_passages):
                links.append((p, a, b, "numeric_match", "numeric", "verified"))
                stats["numeric_links"] += 1
            if status == "unsupported" and any(l[3] == "numeric_match" for l in links):
                status, reasons = "needs_review", reasons + ["numbers_found_in_fulltext_only"]
        row = conn.execute(
            "INSERT INTO claims (paper_id, extraction_run_id, claim_key, claim_type, text, structured, extraction_status, status_reasons) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (paper_id, run["id"], c["key"], c["type"], c["text"], jsonb({**c["structured"], "quote": loc.get("quote")}), status, reasons)).fetchone()
        for p, a, b, origin, ver, est in links:
            conn.execute(
                "INSERT INTO claim_evidence (claim_id, passage_id, evidence_role, origin, quote_start, quote_end, verification, extraction_status) "
                "VALUES (%s,%s,'supports',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (row["id"], p["id"], origin, a, b, ver, est))
        stats["claims"] += 1
        stats[status] += 1
    return stats


def materialize_fulltext(conn, paper_id: int) -> dict:
    """Claims from the latest full-text extraction run. The model cited a passage uid; the verifier already located the quote inside it,
    so the link is exactly (cited passage, offsets). Findings that repeat an abstract finding (same estimate and interval) are skipped:
    that result is already a claim and already corroborated by a numeric_match link."""
    run = conn.execute("SELECT id, output FROM fulltext_runs WHERE paper_id=%s AND status='ok' ORDER BY created_at DESC LIMIT 1", (paper_id,)).fetchone()
    conn.execute("DELETE FROM claims WHERE paper_id=%s AND ft_run_id IS NOT NULL", (paper_id,))
    if not run or not (run["output"] or {}).get("extraction"):
        return {}
    ex = run["output"]["extraction"]
    pid_by_uid = {r["uid"]: r["id"] for r in conn.execute("SELECT id, uid FROM passages WHERE paper_id=%s", (paper_id,))}
    known = {(round(c["structured"].get("effect_value") or 0, 6), round(c["structured"].get("ci_low") or 0, 6), round(c["structured"].get("ci_high") or 0, 6))
             for c in conn.execute("SELECT structured FROM claims WHERE paper_id=%s AND claim_type='finding' AND ft_run_id IS NULL", (paper_id,))
             if c["structured"].get("effect_value") is not None}
    stats = {"ft_claims": 0, "ft_verified": 0, "ft_duplicates": 0}
    items = [("finding", i, f) for i, f in enumerate(ex.get("findings") or [])] + [("limitation", i, f) for i, f in enumerate(ex.get("limitations") or [])]
    for kind, i, f in items:
        if kind == "finding":
            sig = (round(f.get("effect_value") or 0, 6), round(f.get("ci_low") or 0, 6), round(f.get("ci_high") or 0, 6))
            if f.get("effect_value") is not None and sig in known:
                stats["ft_duplicates"] += 1
                continue
            s = {k: f.get(k) for k in ("outcome", "direction", "effect_measure", "effect_value", "ci_low", "ci_high", "p_value", "scope")}
            text, ctype = fmt_finding(f), "finding"
        else:
            s, text, ctype = {"value": f.get("text")}, f"Stated limitation: {f.get('text')}", "limitation"
        status, reasons = claim_status(f.get("verification", "unchecked"), f.get("notes") or [])
        row = conn.execute(
            "INSERT INTO claims (paper_id, ft_run_id, claim_key, claim_type, text, structured, extraction_status, status_reasons) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (paper_id, run["id"], f"ft.{kind}.{i}", ctype, text, jsonb({**s, "quote": f.get("quote"), "passage_uid": f.get("passage_uid"), "source": "fulltext"}),
             status, reasons)).fetchone()
        pid = pid_by_uid.get(f.get("passage_uid"))
        if pid and f.get("char_start") is not None and f.get("verification") in ("exact", "fuzzy"):
            conn.execute("INSERT INTO claim_evidence (claim_id, passage_id, evidence_role, origin, quote_start, quote_end, verification, extraction_status) "
                         "VALUES (%s,%s,'supports','extractor_quote',%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         (row["id"], pid, f["char_start"], f["char_end"], f["verification"], "verified" if status == "verified" else "needs_review"))
        stats["ft_claims"] += 1
        stats["ft_verified"] += status == "verified"
    return stats


def materialize_all() -> dict:
    total: dict[str, int] = {}
    with connect() as conn:
        ids = [r["paper_id"] for r in conn.execute("SELECT DISTINCT paper_id FROM extraction_runs WHERE status='ok' ORDER BY 1")]
        for pid in ids:
            for k, v in materialize_paper(conn, pid).items():
                if isinstance(v, int):
                    total[k] = total.get(k, 0) + v
            for k, v in materialize_fulltext(conn, pid).items():
                total[k] = total.get(k, 0) + v
        conn.commit()
    total["papers"] = len(ids)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(materialize_all())
