"""Model help at answer time, kept on a short leash.

Two uses, both only when the rules are unsure, both cached by input hash, both capped per day:
  read_claim   turn a claim the rules could not read well into exposure / synonyms / measurable outcomes / polarity
  judge_paper  for a paper the rules set aside although it ranked high in retrieval: does it study the claim's exposure, and which of its
               stored findings measure the outcome the claim asks about?
The model never writes evidence. It can only choose among stored findings (by claim id) and propose how to read a claim; the direction,
significance, weight, verdict and every quoted number still come from verified claims and code, and the citation audit runs afterwards.
With no key the cache is replay-only. If an answer is not cached, the cap is reached, or a call fails, the rules-only answer is returned unchanged."""
import hashlib
import json
import os
import re

from ..config import settings
from ..db import connect

PROMPT_VERSION = "assist-2"
_client = None
_injected = False       # tests inject a fake with .complete(key, system, user, schema) -> LLMResponse-like


def set_client(c) -> None:
    global _client, _injected
    _client, _injected = c, c is not None


def enabled() -> bool:
    if _injected:
        return True
    if "PYTEST_CURRENT_TEST" in os.environ or not settings.llm_assist:
        return False
    return True       # with no key this is replay-only: answers already in llm_cache are served, anything else falls back to the rules


def _has_key() -> bool:
    from ..extraction.llm import PROVIDERS
    return bool(settings.llm_api_key) and settings.llm_provider in PROVIDERS


def _get_client():
    global _client
    if _client is None:
        from ..extraction.llm import build_provider, resolved_model
        _client = build_provider(settings.llm_provider, resolved_model(), settings.llm_api_key)
    return _client


def usage_today(conn=None) -> dict:
    def q(c):
        r = c.execute("SELECT count(*) AS calls, coalesce(sum((usage->>'input_tokens')::int),0) AS tin, coalesce(sum((usage->>'output_tokens')::int),0) AS tout "
                      "FROM llm_cache WHERE created_at >= date_trunc('day', now())").fetchone()
        return {"calls": r["calls"], "input_tokens": r["tin"], "output_tokens": r["tout"], "cap": settings.llm_daily_cap}
    if conn is not None:
        return q(conn)
    with connect() as c:
        return q(c)


def call(conn, kind: str, payload: dict, system: str, user: str, schema: dict) -> dict | None:
    """Cached model call. Returns the model's JSON, or None when disabled, capped or failed."""
    if not enabled():
        return None
    key = hashlib.sha256(json.dumps([kind, PROMPT_VERSION, payload], sort_keys=True, default=str).encode()).hexdigest()   # model-agnostic: a shipped cache replays under any setup
    hit = conn.execute("SELECT output FROM llm_cache WHERE key=%s", (key,)).fetchone()
    if hit:
        return hit["output"]
    if not (_injected or _has_key()) or usage_today(conn)["calls"] >= settings.llm_daily_cap:
        return None
    model = getattr(_get_client(), "model", "")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))      # one caller per key: a concurrent identical question waits here, then reads the first one's answer
    hit = conn.execute("SELECT output FROM llm_cache WHERE key=%s", (key,)).fetchone()
    if hit:
        conn.commit()
        return hit["output"]
    try:
        resp = _get_client().complete(key, system, user, schema)
    except Exception:
        conn.rollback()
        return None
    conn.execute("INSERT INTO llm_cache (key, kind, model, request, output, usage) VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb) ON CONFLICT DO NOTHING",
                 (key, kind, resp.model or model, json.dumps(payload, default=str), json.dumps(resp.output), json.dumps(resp.usage or {})))
    conn.commit()
    return resp.output


# ------------------------------------------------------------------------------------------------ 1. read the claim
READ_SCHEMA = {"type": "object", "required": ["exposure", "outcomes", "polarity"], "properties": {
    "exposure": {"type": "string", "description": "the thing being tested, in the words research papers use (e.g. 'vitamin D supplementation')"},
    "exposure_synonyms": {"type": "array", "items": {"type": "string"}, "description": "other single words/short names papers use for the same exposure (max 6)"},
    "outcomes": {"type": "array", "items": {"type": "string"}, "description": "2-6 measurable outcomes papers report that would answer the claim (e.g. 'fractures', 'bone mineral density')"},
    "polarity": {"type": "string", "enum": ["benefit", "harm"], "description": "benefit if the claim says the exposure helps; harm if it says it hurts or raises risk"},
    "tags": {"type": "array", "items": {"type": "string"}, "description": "1-5 topic tags for the claim, chosen ONLY from the allowed list given in the user message"},
    "exposure_less": {"type": "boolean", "description": "true only if the claim is about LESS of the exposure (reducing, cutting, avoiding, low-intake)"}}}
READ_SYSTEM = ("You translate an everyday health claim into the terms nutrition and medical research papers use, so a search over studies can test it. "
               "Do not judge whether the claim is true. Use specific, measurable outcomes (not 'bone strength' but 'fractures', 'bone mineral density'). "
               "Keep the exposure specific: 'vitamin D' is not 'vitamins'. Write each outcome as a short noun phrase whose LAST word is the thing measured, "
               "without filler words like incidence, risk, events or levels ('type 2 diabetes', not 'type 2 diabetes incidence'). For a general health claim about food, drink or a nutrient, "
               "list the broad outcomes such studies report (mortality, cardiovascular disease, cancer, type 2 diabetes, obesity, weight gain, blood pressure) "
               "plus any specific to the claim. Also pick 1-5 topic tags from the allowed list in the message (never invent one). Answer only by calling the tool.")


def read_claim(conn, question: str) -> dict | None:
    q = re.sub(r"\s+", " ", question.strip().lower().rstrip("?. "))
    from .interpret import tag_vocabulary      # not part of the cache key: cached readings written before tags existed still replay (they just carry none)
    out = call(conn, "read_claim", {"q": q}, READ_SYSTEM, f"Claim: {question.strip()}\nAllowed tags: {', '.join(tag_vocabulary())}", READ_SCHEMA)
    if not out or not str(out.get("exposure", "")).strip() or not out.get("outcomes") or out.get("polarity") not in ("benefit", "harm"):
        return None
    out["outcomes"] = [str(o).strip().lower() for o in out["outcomes"] if str(o).strip()][:6]
    out["exposure_synonyms"] = [str(o).strip().lower() for o in (out.get("exposure_synonyms") or []) if str(o).strip()][:6]
    return out


# ------------------------------------------------------------------------------------------------ 2. judge a borderline paper
JUDGE_SCHEMA = {"type": "object", "required": ["studies_exposure", "relevant_finding_ids"], "properties": {
    "studies_exposure": {"type": "boolean", "description": "true if the paper's main intervention/exposure is the claim's exposure (or a direct synonym), alone and not just one part of a multi-component regimen"},
    "relevant_finding_ids": {"type": "array", "items": {"type": "integer"}, "description": "ids of findings that measure an outcome the claim asks about, as an overall (not subgroup/biomarker-association) result"},
    "reason": {"type": "string", "description": "one short sentence"}}}
JUDGE_SYSTEM = ("You check whether a study can be used as evidence for a claim. You are given the claim, how it was read, the study's title, intervention and comparator, "
                "and its stored findings, each with an id. Decide (a) whether the study's main exposure/intervention is the claim's exposure and (b) which finding ids measure an outcome the claim asks about, "
                "overall (not a subgroup or a prognostic association). Be strict: a different supplement, a combination regimen, or an unrelated outcome is not a match. "
                "You never judge direction or significance. Answer only by calling the tool.")


def judge_paper(conn, interp, paper: dict, out: dict) -> dict | None:
    fs = [f for f in out.get("findings", []) if f["status"] == "verified" and not f["subgroup"]][:12]
    if not fs:
        return None
    pico = out.get("pico", {})
    payload = {"claim": interp.question, "exposure": interp.exposure_terms, "outcomes": interp.outcome_terms, "paper": paper["id"], "findings": [f["claim_id"] for f in fs]}
    user = json.dumps({"claim": interp.question, "claim_read_as": {"exposure": " ".join(interp.exposure_terms), "outcomes": interp.outcome_terms, "polarity": interp.polarity},
                       "study": {"title": paper["title"], "design": out.get("design"), "intervention": pico.get("intervention"), "comparator": pico.get("comparator"), "population": pico.get("population")},
                       "findings": [{"id": f["claim_id"], "outcome": f["outcome"], "quote": (f["quote"] or "")[:220]} for f in fs]}, ensure_ascii=False)
    res = call(conn, "judge_paper", payload, JUDGE_SYSTEM, user, JUDGE_SCHEMA)
    if res is None:
        return None
    valid = {f["claim_id"] for f in fs}
    return {"studies_exposure": bool(res.get("studies_exposure")), "relevant_ids": [int(i) for i in res.get("relevant_finding_ids", []) if isinstance(i, int) and i in valid],
            "reason": str(res.get("reason", ""))[:200]}
