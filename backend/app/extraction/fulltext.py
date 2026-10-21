"""Extraction from full-text passages with passage-level citations.

The model is shown selected passages, each prefixed with its stable uid, and must return, for every finding, the uid of the
passage and a verbatim quote from it. The verifier (not the model) then locates the quote inside that passage's stored text:
  exact in the cited passage            -> verified, offsets inside the passage
  exact in a different shown passage    -> accepted with note `passage_corrected` (the model cited the wrong uid)
  not found anywhere                    -> failed (kept, counted, never used)
The model also labels each finding's `scope` (overall effect vs subgroup / interaction / biomarker association), which the
evaluation engine uses to keep subgroup results out of the verdict.
"""
import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ..db import connect, jsonb
from ..ingestion.normalize import sha256
from .llm import LLMClient, LLMFatalError
from .verify import _has_number, locate_quote, numbers_in

log = logging.getLogger("longevidence.fulltext")
FT_PROMPT_VERSION = "ft1"
FT_SCHEMA_VERSION = "ft-1"
MAX_PASSAGES, MAX_CHARS, PER_PASSAGE = 12, 11000, 1800

_STATS = re.compile(r"95\s?%|\bCI\b|hazard ratio|odds ratio|risk ratio|rate ratio|\bHR\b|\bRR\b|\bOR\b|\bP\s?[<=≤]|mean difference", re.I)
_LIMIT = re.compile(r"limitation|should be interpreted|cannot (?:be )?exclude|residual confounding|generali[sz]|small sample|short follow", re.I)


class FTFinding(BaseModel):
    passage_uid: str = Field(description="uid shown in square brackets before the passage the quote comes from")
    outcome: str
    scope: Literal["overall", "subgroup", "exploratory"] = Field(
        description="'overall' = effect of the intervention/exposure on the whole analysed population; 'subgroup' = result within a "
                    "subgroup, by quartile/tertile, interaction, or the association of a biomarker/baseline factor with outcome; "
                    "'exploratory' = post hoc or secondary analysis")
    direction: Literal["favors_intervention", "favors_comparator", "no_difference", "unclear"]
    effect_measure: Literal["HR", "RR", "OR", "MD", "other"] | None = None
    effect_value: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    quote: str = Field(description="Verbatim text (one sentence or one table row) that contains the numbers")
    # verifier-owned
    char_start: int | None = None
    char_end: int | None = None
    verification: str = "unchecked"
    notes: list[str] = Field(default_factory=list)


class FTLimitation(BaseModel):
    passage_uid: str
    text: str
    quote: str
    char_start: int | None = None
    char_end: int | None = None
    verification: str = "unchecked"
    notes: list[str] = Field(default_factory=list)


class FTExtraction(BaseModel):
    findings: list[FTFinding] = Field(default_factory=list, description="Up to 8: the primary outcome first, then key secondary outcomes")
    limitations: list[FTLimitation] = Field(default_factory=list, description="Limitations the authors state themselves, max 4")


VERIFIER = {"char_start", "char_end", "verification", "notes"}


def tool_schema() -> dict:
    s = FTExtraction.model_json_schema()
    for d in s.get("$defs", {}).values():
        d["properties"] = {k: v for k, v in d["properties"].items() if k not in VERIFIER}
    return s


SYSTEM = """You extract results from selected passages of one biomedical paper's full text.
Each passage is shown as [uid] (section) followed by its text. Use ONLY these passages.

Rules:
1. Report findings that have a numeric effect estimate (HR, RR, OR, mean difference, ...) with a confidence interval or p-value. Max 8: the
   primary outcome first, then key secondary outcomes. Skip baseline characteristics and descriptive counts.
2. For each finding give the uid of the passage it comes from and a VERBATIM quote from that passage (one sentence or one table row,
   copied character for character, including the numbers). No ellipsis, no paraphrase.
3. Numbers (estimate, CI bounds, p) must appear in your quote exactly as written. For 'P<0.001' give p_value 0.001.
4. scope: 'overall' only if the result is the effect of the intervention/exposure on the whole analysed population. Results within a
   subgroup, by quartile/tertile, interaction tests, and the association of a baseline biomarker or factor with outcome are 'subgroup'.
   Post hoc or exploratory analyses are 'exploratory'.
5. direction is relative to intervention (or higher exposure) versus comparator, judged from the estimate and interval: an interval
   crossing the null means 'no_difference'. For a harmful exposure, a harmful association is 'favors_comparator'. Use 'unclear' when
   there is no good or bad direction.
6. limitations: only limitations the authors state themselves, each with a verbatim quote. Usually 0-3.
7. If a passage does not state a result, do not invent one. An empty list is a correct answer.
Return one JSON object: {"findings": [...], "limitations": [...]}."""


def select_passages(passages: list[dict]) -> list[dict]:
    """Results/conclusion paragraphs and tables with statistics, plus discussion sentences about limitations."""
    res = [p for p in passages if p["section"] in ("results", "conclusions") and p["kind"] in ("paragraph", "table")]
    scored = sorted(res, key=lambda p: (-int(bool(_STATS.search(p["text"]))), -len(_STATS.findall(p["text"])), p["ordinal"]))
    keep = [p for p in scored if _STATS.search(p["text"])][:MAX_PASSAGES - 2]
    keep += [p for p in scored if p not in keep][: max(0, 3 - len(keep))]
    lim = [p for p in passages if p["section"] == "discussion" and p["kind"] == "paragraph" and _LIMIT.search(p["text"])][:2]
    out = sorted(keep + lim, key=lambda p: p["ordinal"])
    total, final = 0, []
    for p in out:
        t = min(len(p["text"]), PER_PASSAGE)
        if total + t > MAX_CHARS:
            break
        total += t
        final.append(p)
    return final


def user_prompt(title: str, passages: list[dict]) -> str:
    blocks = [f"[{p['uid']}] ({p['section']}{' · ' + p['label'] if p['label'] else ''})\n{p['text'][:PER_PASSAGE]}" for p in passages]
    return f"Title: {title}\n\nPassages:\n\n" + "\n\n".join(blocks)


def _locate(quote: str, uid: str, shown: dict[str, dict]) -> tuple[str, str | None, int | None, int | None, list[str]]:
    """-> (verification, uid_used, start, end, notes)"""
    p = shown.get(uid)
    notes: list[str] = []
    if p:
        v, a, b = locate_quote(quote, p["text"])
        if v != "failed":
            return v, uid, a, b, notes
    else:
        notes.append("unknown_passage_uid")
    for u, q in shown.items():
        if u == uid:
            continue
        v, a, b = locate_quote(quote, q["text"])
        if v == "exact":
            return v, u, a, b, notes + ["passage_corrected"]
    return "failed", None, None, None, notes + ["quote_not_in_cited_passage"]


def verify_ft(ex: FTExtraction, shown: dict[str, dict]) -> FTExtraction:
    for f in ex.findings:
        f.verification, uid, f.char_start, f.char_end, f.notes = _locate(f.quote, f.passage_uid, shown)
        if uid:
            f.passage_uid = uid
        if f.verification == "failed":
            continue
        nums = numbers_in(f.quote)
        for k in ("effect_value", "ci_low", "ci_high", "p_value"):
            v = getattr(f, k)
            if v is not None and not _has_number(float(v), nums):
                f.verification = "failed"
                f.notes.append(f"number_not_in_quote:{k}")
        if f.ci_low is not None and f.ci_high is not None and f.effect_value is not None and not (f.ci_low <= f.effect_value <= f.ci_high):
            f.notes.append("sanity:ci_excludes_estimate")
        if f.p_value is not None and not (0 <= f.p_value <= 1):
            f.notes.append("sanity:p_out_of_range")
    for l in ex.limitations:
        l.verification, uid, l.char_start, l.char_end, l.notes = _locate(l.quote, l.passage_uid, shown)
        if uid:
            l.passage_uid = uid
    return ex


def run_paper(conn, paper_id: int, client: LLMClient) -> str:
    """Extract one paper's full text (cached by input hash). Returns 'cached' | status | 'no_fulltext'."""
    doc = conn.execute("SELECT id FROM documents WHERE paper_id=%s AND kind='pmc_jats'", (paper_id,)).fetchone()
    if not doc:
        return "no_fulltext"
    title = conn.execute("SELECT title FROM papers WHERE id=%s", (paper_id,)).fetchone()["title"]
    passages = conn.execute("SELECT uid, ordinal, section, kind, label, text FROM passages WHERE document_id=%s ORDER BY ordinal", (doc["id"],)).fetchall()
    chosen = select_passages(passages)
    if not chosen:
        return "no_candidate_passages"
    shown = {p["uid"]: p for p in chosen}
    prompt = user_prompt(title, chosen)
    ihash = sha256(prompt, client.model, FT_PROMPT_VERSION, FT_SCHEMA_VERSION, SYSTEM)
    row = conn.execute("SELECT id, status FROM fulltext_runs WHERE paper_id=%s AND model_name=%s AND prompt_version=%s AND schema_version=%s AND input_hash=%s",
                       (paper_id, client.model, FT_PROMPT_VERSION, FT_SCHEMA_VERSION, ihash)).fetchone()
    if row and row["status"] == "ok":
        return "cached"
    status, out, usage, err, last = "error", None, {}, None, None
    for attempt in range(2):
        try:
            resp = client.complete(ihash if attempt == 0 else ihash + ".repair", SYSTEM,
                                   prompt if attempt == 0 else f"{prompt}\n\nYour previous output failed validation:\n{last}\nReturn a corrected full output.",
                                   tool_schema())
        except LLMFatalError:
            raise
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            break
        for k, v in resp.usage.items():
            usage[k] = usage.get(k, 0) + v
        raw = resp.output
        for k in ("findings", "limitations"):          # some models double-encode lists as strings
            if isinstance(raw.get(k), str):
                try:
                    raw[k] = json.loads(raw[k])
                except ValueError:
                    pass
        try:
            ex = verify_ft(FTExtraction.model_validate(raw), shown)
            status, err = "ok", None
            out = {"extraction": ex.model_dump(mode="json"), "raw": resp.output, "shown_uids": list(shown)}
            break
        except ValidationError as e:
            last, status, err = str(e)[:1200], "invalid", str(e)[:1200]
    conn.execute(
        "INSERT INTO fulltext_runs (paper_id, document_id, model_name, prompt_version, schema_version, input_hash, output, status, usage, error) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (paper_id, model_name, prompt_version, schema_version, input_hash) "
        "DO UPDATE SET output=EXCLUDED.output, status=EXCLUDED.status, usage=EXCLUDED.usage, error=EXCLUDED.error, created_at=now()",
        (paper_id, doc["id"], client.model, FT_PROMPT_VERSION, FT_SCHEMA_VERSION, ihash, jsonb(out), status, jsonb(usage), err))
    conn.commit()
    return status


def run_all(client: LLMClient, workers: int = 1, only: list[int] | None = None, limit: int | None = None) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    counts: dict[str, int] = {}
    with connect() as conn:
        ids = [r["paper_id"] for r in conn.execute("SELECT paper_id FROM documents WHERE kind='pmc_jats' ORDER BY paper_id")]
    ids = [i for i in ids if not only or i in only]
    if limit:
        ids = ids[:limit]

    def one(pid):
        with connect() as c:
            return pid, run_paper(c, pid, client)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = [pool.submit(one, i) for i in ids]
        try:
            for fut in as_completed(futs):
                pid, st = fut.result()
                counts[st] = counts.get(st, 0) + 1
                log.info("paper %s -> %s (%d/%d)", pid, st, sum(counts.values()), len(ids))
        except BaseException:
            for f in futs:
                f.cancel()
            raise
    return counts


if __name__ == "__main__":
    import argparse
    from .llm import default_client
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--paper", type=int, action="append")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    try:
        print(run_all(default_client(), a.workers, a.paper, a.limit))
    except LLMFatalError as e:
        raise SystemExit(f"aborted (completed papers are saved; re-run to resume): {e}")
