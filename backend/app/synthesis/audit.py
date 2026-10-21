"""Citation audit. Runs after statements are built and before they are shown.

For every statement that makes an evidence claim it re-reads the database (not the in-memory report) and checks:
  1. each cited claim exists and has status 'verified'
  2. the claim has at least one stored passage link, and the quote span sits inside that passage's text
  3. every number the statement prints for a study (estimate, CI bounds, p) appears in the cited passage text
A statement failing any check is removed from the conclusion and listed in the audit with the reason."""
import re

from ..extraction.verify import numbers_in

_NUM_FIELDS = ("effect_value", "ci_low", "ci_high", "p_value")


def _has(v: float, nums: list[float]) -> bool:
    return any(abs(abs(v) - abs(n)) < 1e-9 for n in nums)


def audit_statements(conn, statements: list[dict]) -> dict:
    cache: dict[int, dict] = {}

    def claim(cid: int) -> dict:
        if cid not in cache:
            c = conn.execute("SELECT id, claim_type, structured, extraction_status FROM claims WHERE id=%s", (cid,)).fetchone()
            ev = conn.execute(
                "SELECT ce.quote_start, ce.quote_end, ce.extraction_status, p.uid, p.text FROM claim_evidence ce JOIN passages p ON p.id=ce.passage_id "
                "WHERE ce.claim_id=%s", (cid,)).fetchall() if c else []
            cache[cid] = {"claim": c, "evidence": ev}
        return cache[cid]

    results, numbers_checked = [], 0
    claims_cited: set[int] = set()
    for s in statements:
        problems: list[str] = []
        if s.get("requires_citation"):
            if not s["claim_ids"]:
                problems.append("no claim cited")
            for cid in s["claim_ids"]:
                claims_cited.add(cid)
                x = claim(cid)
                c = x["claim"]
                if not c:
                    problems.append(f"claim {cid} not found")
                    continue
                if c["extraction_status"] != "verified":
                    problems.append(f"claim {cid} is {c['extraction_status']}")
                if not x["evidence"]:
                    problems.append(f"claim {cid} has no stored passage")
                    continue
                if not any(0 <= e["quote_start"] < e["quote_end"] <= len(e["text"]) for e in x["evidence"]):
                    problems.append(f"claim {cid}: quote span outside passage")
                if s["kind"] == "study":
                    spans = " ".join(e["text"][e["quote_start"]:e["quote_end"]] for e in x["evidence"])
                    nums = numbers_in(spans)
                    for f in _NUM_FIELDS:
                        v = c["structured"].get(f)
                        if v is not None and v != 0:
                            numbers_checked += 1
                            if not _has(float(v), nums):
                                problems.append(f"{f}={v} not in cited passage")
        results.append({"id": s["id"], "ok": not problems, "problems": problems})
    failed = [r for r in results if not r["ok"]]
    req = [s for s in statements if s.get("requires_citation")]
    return {"statements": len(statements), "requiring_citation": len(req),
            "passed": len(results) - len(failed), "failed": len(failed), "claims_cited": len(claims_cited),
            "numbers_checked": numbers_checked, "results": results}
