"""Who the evidence applies to, at what dose/duration, and what it says about safety.

Everything here is read from stored records of the studies that were counted: PICO fields come from verified claims, and safety sentences are
located verbatim in a stored passage (retrieval only, never counted toward the verdict). Nothing is generated."""
import re

SAFETY_RX = re.compile(
    r"\b(adverse (?:event|effect|reaction)s?|side[- ]effects?|well[- ]tolerated|tolerab(?:le|ility)|safety|safe\b|serious adverse|"
    r"harm(?:s|ful)?|toxicit(?:y|ies)|incidental findings?|false[- ]positives?|overdiagnos\w+|unnecessary (?:biops|follow|investigation|procedure)\w*|"
    r"over-?treatment|discontinu\w+ (?:due|because)|withdrew|dropouts?)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
MAX_SAFETY = 6
MAX_LIST = 6


def _short(v, n=160) -> str:
    t = " ".join(str(v).split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def _group(counted: list[dict], key: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for s in counted:
        v = (s.get("pico") or {}).get(key)
        if not v:
            continue
        k = _short(v).lower()
        e = seen.setdefault(k, {"text": _short(v), "paper_ids": [], "n": 0})
        e["paper_ids"].append(s["paper_id"])
        e["n"] += s.get("sample_size") or 0
    return sorted(seen.values(), key=lambda e: (-len(e["paper_ids"]), -e["n"]))[:MAX_LIST]


def _safety(conn, counted: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in sorted(counted, key=lambda s: -s["weight"]):
        if len(out) >= MAX_SAFETY:
            break
        rows = conn.execute(
            "SELECT p.uid, p.text, p.section FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.paper_id=%s "
            "AND p.kind IN ('paragraph','abstract_section') AND p.section NOT IN ('methods','funding_coi') "
            "ORDER BY d.kind DESC, p.ordinal", (s["paper_id"],)).fetchall()
        for r in rows:
            hit = None
            for sent in _SENT.split(r["text"]):
                if SAFETY_RX.search(sent) and 40 <= len(sent) <= 400:
                    hit = sent.strip()
                    break
            if hit:
                a = r["text"].find(hit)
                out.append({"paper_id": s["paper_id"], "title": s["title"], "year": s.get("year"), "passage_uid": r["uid"],
                            "section": r["section"], "quote": hit, "quote_start": a, "quote_end": a + len(hit)})
                break
    return out


def build_caveats(conn, counted: list[dict]) -> dict:
    if not counted:
        return {"applies_to": None, "populations": [], "regimens": [], "durations": [], "safety": [], "notes": []}
    designs: dict[str, int] = {}
    for s in counted:
        designs[s.get("design_label") or s.get("design") or "other"] = designs.get(s.get("design_label") or s.get("design") or "other", 0) + 1
    total_n = sum(s.get("sample_size") or 0 for s in counted)
    reported_n = sum(1 for s in counted if s.get("sample_size"))
    safety = _safety(conn, counted)
    notes = []
    if not safety:
        notes.append("None of the counted studies state anything on safety or harms in the text we stored. That is absence of reporting, not evidence of safety.")
    if reported_n < len(counted):
        notes.append(f"Sample size was not reported for {len(counted) - reported_n} of {len(counted)} counted studies.")
    if all((s.get("basis") == "abstract") for s in counted):
        notes.append("All counted studies were read from the abstract only; dose, duration and adverse events are often missing there.")
    return {
        "applies_to": {"studies": len(counted), "participants": total_n or None, "participants_reported_in": reported_n,
                       "designs": [{"design": d, "n": n} for d, n in sorted(designs.items(), key=lambda x: -x[1])]},
        "populations": _group(counted, "population"),
        "regimens": _group(counted, "intervention"),
        "durations": _group(counted, "follow_up"),
        "safety": safety,
        "notes": notes,
    }
