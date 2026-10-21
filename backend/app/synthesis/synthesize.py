"""Question -> evidence report.

Pipeline (all deterministic, no LLM at answer time):
  retrieve   papers whose title/abstract cover the question's concepts
  select     per paper, the verified finding that answers the question (claims whose quote or numbers are NOT verified are
             listed but never counted)
  appraise   design, size, bias signals (assess.py), statistical uncertainty per finding
  compare    stance of each finding relative to the question (supports / contradicts / contextualizes), outcome clusters,
             conflicts between studies with the PICO differences side by side
  conclude   a verdict and templated statements built ONLY from selected claims; every statement lists the claim ids it uses
  audit      (audit.py) re-resolves every cited claim to its stored passage and re-checks the numbers before anything is shown

The language model's job ended at extraction. Nothing in this module writes free text about a paper's content.
"""
import hashlib
import math
import json
import re
from collections import defaultdict

from ..db import jsonb
from ..extraction.verify import numbers_in
from .assess import (DESIGN_RANK, DESIGN_WEIGHT, EXPERIMENTAL, ROB_WEIGHT, finding_stats, rob_level, screen_signals, size_weight)
from .interpret import Interpretation, interpret
from .outcomes import TIER_LABEL, match_outcome, tier_of
from .scope import PROGNOSTIC_RX, distribute_lists, _less_cue, Exposure, exposure_less, has_any, has_term, scope_exclusion, strip_terms

ENGINE_VERSION = "4"
VERDICT_RULES = {
    "min_studies": 3,
    "mixed_if_each_at_least": 0.20, "mixed_min_studies_each_side": 2,
    "supported": 0.65, "leans": 0.40,
    "description": "Weighted shares of counted studies (weight = design x sample size x bias screen). 'Mixed' if both the supporting and the "
                   "contradicting share are >= 0.20; 'Supported'/'Contradicted' if one side >= 0.65; 'Leans' if >= 0.40; otherwise 'No clear effect'. "
                   "Fewer than 3 counted studies is always 'Insufficient evidence'.",
}
DESIGN_LABEL = {"rct": "RCT", "rct_secondary_analysis": "RCT secondary analysis", "cohort": "Cohort", "meta_analysis": "Meta-analysis",
                "cross_sectional": "Cross-sectional", "case_control": "Case-control", "other": "Other", "unknown": "Unclassified"}
PUBMED_DESIGN = [("Meta-Analysis", "meta_analysis"), ("Systematic Review", "meta_analysis"), ("Randomized Controlled Trial", "rct"),
                 ("Observational Study", "cohort")]
COUNTED = ("verified",)

# ------------------------------------------------------------------------------------------------ text helpers
_SUFFIX = re.compile(r"(ations?|ation|ings?|ing|ies|ied|es|ed|s)$")


def stem(w: str) -> str:
    w = w.lower()
    return _SUFFIX.sub("", w) if len(w) > 4 else w


def tokens(s: str) -> list[str]:
    from .interpret import STOP
    return [stem(w) for w in re.findall(r"[a-z0-9][a-z0-9-]*", s.lower()) if w not in STOP and len(w) > 2]


def outcome_matches(outcome: str, terms: list[str], free: bool = False) -> bool:
    """Does a finding's outcome answer the question's outcome? Matches on the OUTCOME HEAD only (see outcomes.py), so exposure words in the
    rest of the string ('IBD onset, high cholesterol intake') cannot count as the outcome."""
    return match_outcome(outcome, terms, free)[0]


def fmt_num(x: float) -> str:
    return f"{x:g}"


def fmt_estimate(s: dict, omit_p: bool = False) -> str:
    bits = []
    if s.get("effect_value") is not None:
        bits.append(f"{s.get('effect_measure') or 'effect'} {fmt_num(s['effect_value'])}")
    if s.get("ci_low") is not None and s.get("ci_high") is not None:
        bits.append(f"(95% CI {fmt_num(s['ci_low'])} to {fmt_num(s['ci_high'])})")
    if s.get("p_value") is not None and not omit_p:
        bits.append(f"p = {fmt_num(s['p_value'])}")
    return " ".join(bits)


CONTRAST_RX = re.compile(r"\bQ[1-5]\b|quartile|tertile|quintile|highest|lowest|\btop\b|bottom|high(?:er)? (?:vs|versus|compared)|per \d+ ?(?:g|mg)|per (?:serving|SD|unit|day)", re.I)
STRATUM2_RX = re.compile(r"\b(?:men|women|males?|females?|boys|girls)\b|\baged \d|interaction|\bby (?:sex|age|region)|region|APOE|genotype|PRS", re.I)
STRATUM_RX = re.compile(r"sensitivity analys|\baged \d|\b(?:by|according to) (?:sex|age|gender)\b|\bin those with\b|,\s*(?:in\s+)?(?:women|men|females?|males?)\s*$", re.I)   # all designs
SUBGROUP_RX = re.compile(r"\bQ[1-4]\b|quartile|tertile|quintile|subgroup|stratum|strata|stratified|interaction|by baseline|per[- ]SD|per[- ]unit|"
                         r"per \d|per[- ]standard|prognostic|effect modif|according to (?:baseline|level)|\bby (?:serum|plasma|level|tertile|quartile)", re.I)


def norm_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


COMBO_RX = re.compile(r"\bplus\b|combination|combined|polypill|containing|fixed[- ]dose|\+|add-on", re.I)


def exposure_matches(interp: Interpretation, title: str, pico: dict, design: str | None = None) -> tuple[bool, str | None]:
    """Preset questions only: the first concept group is the exposure/intervention. It must be what the paper studies:
    in the title, or the extracted intervention/comparator. Merely appearing in the abstract (background, co-therapy) does not count,
    and neither does being one component of a combination regimen when the title does not name it."""
    if interp.source != "preset":
        if not interp.exposure_terms:
            return True, None
        from ..search.bm25 import tokenize
        from ..search.synonyms import expand
        # In randomized trials the extracted intervention decides (a drug trial whose title mentions 'dietary sodium' as an effect modifier is not about
        # salt). Observational studies and reviews rarely have a real 'intervention', so there the title also counts.
        interv = str(pico.get("intervention") or "")
        trial = design in EXPERIMENTAL
        parts = [interv, str(pico.get("comparator") or "")] + ([] if (trial and interv) else [title or ""])
        hay = set(tokenize(" ".join(parts)))
        if interp.exposure_alias and any(expand(t) & hay for t in interp.exposure_alias):
            return True, None                                   # e.g. 'processed food' is satisfied by 'ultra-processed'
        if interp.exposure_words:                                # most exposure WORDS must be present (a word matches via any of its tokens or synonyms)
            hit = sum(1 for toks in interp.exposure_words if any(expand(t) & hay for t in toks))
            need = max(1, math.ceil(0.67 * len(interp.exposure_words)))
            ok = hit >= need
        else:
            need = max(1, -(-len(interp.exposure_terms) // 2))
            ok = sum(1 for t in interp.exposure_terms if expand(t) & hay) >= need
        if ok:
            return True, None
        return False, "exposure_not_studied"
    if not interp.concepts:
        return True, None
    ex = Exposure(interp)
    interv = str(pico.get("intervention") or "")
    comp = str(pico.get("comparator") or "")
    t_hit, i_hit, c_hit = ex.hit(title or ""), ex.hit(interv), ex.hit(comp)       # whole-word matches; 'unsweetened'/'poultry'/'plant-based oils' are stripped first
    if not i_hit and interv.strip() and ex.not_terms and has_any(distribute_lists(interv), ex.not_terms):
        return False, "exposure_not_studied"                    # the tested intervention is the look-alike ('pescatarian', 'preserved vegetables'), whatever the title says
    if i_hit:
        if not t_hit and COMBO_RX.search(interv):
            return False, "exposure_only_part_of_combination"
        return True, None
    if c_hit:
        if _less_cue(ex, comp) or _NO_ARM.search(comp):
            return False, "exposure_not_studied"                # 'no X' / reduced X is the comparator: the intervention is something else
        return True, None                                        # the exposure is the comparator arm; appraise_paper flips the orientation
    if t_hit:
        trialish = design in EXPERIMENTAL or design in (None, "other", "unknown")
        if trialish and interv.strip():
            return False, "exposure_not_studied"                 # the title names it, but the intervention that was tested is something else
        return True, None
    return False, "exposure_not_studied"


_NO_ARM = re.compile(r"\b(?:no|non|without|free of|zero|absence of)\b", re.I)


# ------------------------------------------------------------------------------------------------ retrieval
def retrieve_hybrid(conn, interp: Interpretation, limit: int = 40) -> list[dict]:
    """Free-text questions: candidates from the hybrid index (BM25 keyword + vector similarity over titles, abstracts and full-text passages).
    Found by both indexes -> relevance 1.0; by one only -> 0.8 (counts toward the 'indirectness' check)."""
    from ..search.index import get_index
    hits = get_index().search(interp.search_text or interp.question, "hybrid", limit=limit)
    if not hits:
        return []
    by_id = {h.paper_id: h for h in hits}
    rows = conn.execute(
        "SELECT p.id, p.title, p.journal, p.publication_date, p.source_metadata, "
        "(SELECT identifier_value FROM paper_identifiers WHERE paper_id=p.id AND identifier_type='pmid' LIMIT 1) AS pmid "
        "FROM papers p WHERE p.id = ANY(%s)", (list(by_id),)).fetchall()
    for r in rows:
        r["relevance"] = 1.0 if len(by_id[r["id"]].via) == 2 else 0.8
    return sorted(rows, key=lambda r: -by_id[r["id"]].score)


def retrieve_papers(conn, interp: Interpretation) -> list[dict]:
    """Preset questions: papers whose title+abstract cover every concept group (hand-written, high precision).
    Free-text questions: hybrid keyword + vector retrieval."""
    if interp.source != "preset":
        return retrieve_hybrid(conn, interp)
    groups = interp.concepts
    if not groups:
        return []
    cols, params = [], []
    for g in groups:
        qs = " || ".join("phraseto_tsquery('english', %s)" for _ in g)
        cols.append(f"(to_tsvector('english', coalesce(p.title,'')||' '||coalesce(p.abstract,'')) @@ ({qs}))")
        params += g
    sql = (f"SELECT p.id, p.title, p.journal, p.publication_date, p.source_metadata, "
           f"(SELECT identifier_value FROM paper_identifiers WHERE paper_id=p.id AND identifier_type='pmid' LIMIT 1) AS pmid, "
           f"ARRAY[{', '.join(cols)}] AS hit FROM papers p")
    rows = conn.execute(sql, params).fetchall()
    out = []
    n = len(groups)
    for r in rows:
        matched = sum(1 for h in r["hit"] if h)
        cov = matched / n
        ok = matched == n if interp.source == "preset" else (cov >= 0.67 and matched >= min(2, n))
        if ok:
            r["relevance"] = round(cov, 2)
            out.append(r)
    return out


def context_passages(conn, paper_id: int, interp: Interpretation, k: int = 2) -> list[dict]:
    """Retrieval-only passages (full text results/discussion) most related to the question terms: shown as context, never counted."""
    terms = " | ".join(" & ".join(re.sub(r"[^a-z0-9 ]", " ", t.lower()).split()) for t in interp.outcome_terms if re.sub(r"[^a-z0-9 ]", "", t).strip())
    if not terms:
        return []
    return conn.execute(
        "SELECT p.uid, p.section, p.section_title, ts_rank_cd(to_tsvector('english', p.text), to_tsquery('english', %s)) AS r "
        "FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.paper_id=%s AND d.kind='pmc_jats' AND p.kind='paragraph' "
        "AND p.section IN ('results','conclusions') AND to_tsvector('english', p.text) @@ to_tsquery('english', %s) "
        "ORDER BY r DESC LIMIT %s", (terms, paper_id, terms, k)).fetchall()


# ------------------------------------------------------------------------------------------------ per-paper
def _load_claims(conn, paper_id: int) -> list[dict]:
    """Claims of the latest abstract extraction, then those of the latest full-text extraction (abstract claims first: they win the
    'headline finding' tie because the abstract states the primary result first)."""
    claims = conn.execute(
        "SELECT c.id, c.claim_key, c.claim_type, c.text, c.structured, c.extraction_status, c.status_reasons FROM claims c WHERE c.paper_id=%s AND ("
        "c.extraction_run_id=(SELECT extraction_run_id FROM claims WHERE paper_id=%s AND extraction_run_id IS NOT NULL ORDER BY id DESC LIMIT 1) OR "
        "c.ft_run_id=(SELECT ft_run_id FROM claims WHERE paper_id=%s AND ft_run_id IS NOT NULL ORDER BY id DESC LIMIT 1)) "
        "ORDER BY (c.ft_run_id IS NOT NULL), c.id", (paper_id, paper_id, paper_id)).fetchall()
    for c in claims:
        c["evidence"] = conn.execute(
            "SELECT ce.id, ce.evidence_role, ce.origin, ce.quote_start, ce.quote_end, ce.verification, ce.extraction_status, "
            "p.uid AS passage_uid, p.section, p.section_title, p.kind AS passage_kind, p.label, d.kind AS doc_kind "
            "FROM claim_evidence ce JOIN passages p ON p.id=ce.passage_id JOIN documents d ON d.id=p.document_id "
            "WHERE ce.claim_id=%s ORDER BY (ce.origin='extractor_quote') DESC, ce.id", (c["id"],)).fetchall()
    return claims


def _claim(claims: list[dict], ctype: str) -> dict | None:
    return next((c for c in claims if c["claim_type"] == ctype), None)


def _design(claims, pubtypes) -> tuple[str, str]:
    c = _claim(claims, "design")
    if c and c["extraction_status"] != "unsupported":
        return c["structured"]["value"], "extracted"
    for key, val in PUBMED_DESIGN:
        if key in pubtypes:
            return val, "pubmed"
    return "unknown", "none"


def stance_of(f: dict, stats, polarity: str, exposure_less: bool = False, paper_less: bool = False) -> tuple[str, str, list[str]]:
    """-> (stance, evidence_role, flags). stance: favorable|unfavorable|null|unclear (relative to what the question asks).

    Normalises direction to one scale, 'is MORE of the exposure better?':
      paper:  'favors_intervention' means the intervention arm did better. If the intervention REDUCES the exposure (paper_less), that
              is evidence that LESS is better.
      claim:  harm polarity -> 'more is worse'; benefit polarity -> 'more is better', unless the claim itself is about less of the exposure
              (exposure_less: 'does reducing salt lower blood pressure') -> 'less is better'.
    The result supports the claim when the two agree."""
    flags = list(stats.flags)
    d = f.get("direction")
    if d == "unclear":
        return "unclear", "contextualizes", flags
    if stats.significant is False:
        if d in ("favors_intervention", "favors_comparator"):
            flags.append("direction_label_overridden_by_interval")
        return "null", "contextualizes", flags
    if d == "no_difference":
        if stats.significant:
            flags.append("label_says_no_difference_but_interval_excludes_null")
        return "null", "contextualizes", flags
    more_better_paper = (d == "favors_intervention") != paper_less
    claim_more_better = polarity == "benefit" and not exposure_less
    if paper_less != exposure_less and polarity == "benefit":
        flags.append("direction_normalised_for_reduction")
    favorable = more_better_paper == claim_more_better
    return ("favorable", "supports", flags) if favorable else ("unfavorable", "contradicts", flags)


def _scope(interp, title, pico, head) -> dict | None:
    r = scope_exclusion(interp, title, pico, head)
    return {"code": r[0], "detail": r[1]} if r else None


def _pick(findings: list[dict]) -> tuple[dict | None, dict]:
    """The paper's candidate findings (on the asked outcome, verified, overall rather than subgroup, in scope), one per outcome tier.
    The default headline is the best-tier candidate; select_tier() later picks the tier the whole topic is judged on."""
    by: dict[int, dict] = {}
    for f in findings:
        if f["outcome_relevant"] and f["status"] in COUNTED and not f["subgroup"] and not f.get("scope_excluded"):
            by.setdefault(f["tier"], f)
    return (by[min(by)] if by else None), {str(t): f["claim_id"] for t, f in sorted(by.items())}


def appraise_paper(conn, paper: dict, interp: Interpretation, judge=None) -> dict:
    pid = paper["id"]
    claims = _load_claims(conn, pid)
    pubtypes = (paper["source_metadata"] or {}).get("pubmed", {}).get("publication_types", [])
    base = {"paper_id": pid, "title": paper["title"], "journal": paper["journal"], "pmid": paper["pmid"],
            "year": paper["publication_date"].year if paper["publication_date"] else None, "relevance": paper["relevance"]}
    if not claims:
        return {**base, "counted": False, "excluded_reason": "not_extracted", "claims_seen": 0}
    design, design_src = _design(claims, pubtypes)
    nclaim = _claim(claims, "sample_size")
    n = nclaim["structured"]["value"] if nclaim and nclaim["extraction_status"] != "unsupported" else None
    passages = conn.execute("SELECT p.uid, p.text, p.section, d.kind AS doc_kind FROM passages p JOIN documents d ON d.id=p.document_id "
                            "WHERE p.paper_id=%s ORDER BY d.kind DESC, p.ordinal", (pid,)).fetchall()
    has_ft = any(p["doc_kind"] == "pmc_jats" for p in passages)
    signals = screen_signals(design, passages, has_ft)
    rob, rob_reasons = rob_level(design, signals)
    sw, size_label = size_weight(n)
    parts = {"design": DESIGN_WEIGHT.get(design, 0.2), "size": sw, "bias": ROB_WEIGHT[rob]}
    weight = round(parts["design"] * parts["size"] * parts["bias"], 3)

    from .interpret import exposure_is_less
    from .scope import _CALORIE
    interv_txt = str((_claim(claims, "intervention") or {}).get("structured", {}).get("value") or "")
    comp_txt = str((_claim(claims, "comparator") or {}).get("structured", {}).get("value") or "")
    legacy_less = exposure_is_less(_CALORIE.sub(" ", interv_txt))         # parsed (free-text) questions keep the older whole-intervention reading
    expo = Exposure(interp) if interp.source == "preset" else None
    findings = []
    for c in claims:
        if c["claim_type"] != "finding":
            continue
        s = c["structured"]
        rel, tier, head = match_outcome(s.get("outcome", ""), interp.outcome_terms, free=interp.source != "preset")
        stats = finding_stats(s)
        if expo is not None:
            paper_less, basis = exposure_less(expo, str(s.get("outcome") or ""), interv_txt, comp_txt)
        else:
            paper_less, basis = legacy_less, ("intervention reduces the exposure" if legacy_less else "")
        stance, role, flags = stance_of(s, stats, interp.polarity, interp.exposure_less, paper_less)
        txt = f"{s.get('outcome', '')} {s.get('quote') or ''}"[:600]
        sub = bool(STRATUM_RX.search(txt)) or bool(PROGNOSTIC_RX.search(str(s.get('outcome') or ''))) or (design in EXPERIMENTAL and bool(SUBGROUP_RX.search(txt)))
        if s.get("scope") == "subgroup":                 # the full-text extractor labels scope itself
            # In observational studies the highest-vs-lowest quartile/tertile contrast IS the main exposure comparison; only real strata
            # (sex, age band, region, interaction) are subgroups there.
            contrast = bool(CONTRAST_RX.search(txt)) and not STRATUM2_RX.search(txt)
            sub = not (design not in EXPERIMENTAL and contrast)
        if sub:
            flags.append("subgroup_or_prognostic_result")
        if s.get("scope") == "exploratory":
            flags.append("exploratory_analysis")
        findings.append({"claim_id": c["id"], "claim_key": c["claim_key"], "outcome": s.get("outcome"), "direction": s.get("direction"),
                         "effect_measure": s.get("effect_measure"), "effect_value": s.get("effect_value"), "ci_low": s.get("ci_low"),
                         "ci_high": s.get("ci_high"), "p_value": s.get("p_value"), "quote": s.get("quote"),
                         "status": c["extraction_status"], "status_reasons": c["status_reasons"], "outcome_relevant": rel, "outcome_head": head, "tier": tier,
                         "orientation": {"exposure_less": bool(paper_less), "basis": basis}, "scope_excluded": None,
                         "significant": stats.significant, "sig_basis": stats.basis, "precision": stats.precision, "se": stats.se,
                         "stance": stance, "evidence_role": role, "flags": flags, "subgroup": sub,
                         "estimate": fmt_estimate(s, omit_p="p_value_and_ci_disagree" in flags),
                         "evidence": [{k: e[k] for k in ("passage_uid", "origin", "quote_start", "quote_end", "verification", "extraction_status",
                                                        "section", "section_title", "label", "doc_kind")} for e in c["evidence"]]})
    pico = {t: (_claim(claims, t) or {}).get("structured", {}).get("value") for t in ("population", "intervention", "comparator", "follow_up")}
    pico_ids = {t: (_claim(claims, t) or {}).get("id") for t in pico}
    flagged = [c["claim_key"] for c in claims if c["claim_type"] == "design" and "design_disagrees_with_pubmed" in (c["status_reasons"] or [])]
    for f in findings:                                       # scope is judged per finding (an infant-outcome finding in a paper that also has an adult one)
        if f["outcome_relevant"] and f["status"] in COUNTED and not f["subgroup"]:
            f["scope_excluded"] = _scope(interp, paper["title"], pico, f["outcome_head"])
    headline, tier_ids = _pick(findings)
    out = {**base, "design": design, "design_source": design_src, "design_label": DESIGN_LABEL.get(design, design), "sample_size": n,
           "size_label": size_label, "weight": weight, "weight_parts": parts, "rob": rob, "rob_reasons": rob_reasons,
           "signals": [s.__dict__ for s in signals], "basis": "fulltext" if has_ft else "abstract", "pico": pico, "pico_claim_ids": pico_ids,
           "findings": findings, "headline": headline, "tier_claim_ids": tier_ids, "claims_seen": len(claims), "design_flags": flagged,
           "design_claim_id": (_claim(claims, "design") or {}).get("id"), "sample_size_claim_id": (nclaim or {}).get("id")}
    exp_ok, exp_reason = exposure_matches(interp, paper["title"], pico, design)
    near = False
    if judge is not None and not exp_ok and exp_reason == "exposure_not_studied" and interp.exposure_words:       # partial exposure match only: otherwise clearly a different topic
        from ..search.bm25 import tokenize as _tk
        from ..search.synonyms import expand as _ex
        hay = set(_tk(" ".join(str(pico.get(k) or "") for k in ("intervention", "comparator")) + " " + (paper["title"] or "")))
        near = any(_ex(t) & hay for toks in interp.exposure_words for t in toks)
    if judge is not None and (near or exp_ok and headline is None and not any(f["outcome_relevant"] for f in findings)):
        j = judge(paper, out)                             # borderline: ranked high in retrieval but the rules set it aside; the model may only choose among stored findings
        if j and j["studies_exposure"]:
            for f in findings:
                if f["claim_id"] in j["relevant_ids"] and not f["outcome_relevant"]:
                    f["outcome_relevant"] = True
                    f["flags"].append("outcome_matched_by_model")
            for f in findings:
                if f["outcome_relevant"] and f["status"] in COUNTED and not f["subgroup"] and f["scope_excluded"] is None and f["flags"].count("outcome_matched_by_model"):
                    f["scope_excluded"] = _scope(interp, paper["title"], pico, f["outcome_head"])
            cand_head, cand_ids = _pick(findings)
            if cand_head:
                headline = out["headline"] = cand_head
                out["tier_claim_ids"] = cand_ids
                exp_ok = True
                out["model_judged"] = {"reason": j["reason"], "exposure": j["studies_exposure"], "findings": j["relevant_ids"]}
    if not exp_ok:
        out["counted"], out["excluded_reason"] = False, exp_reason
        return out
    if headline is None:
        rel = [f for f in findings if f["outcome_relevant"]]
        scoped = next((f for f in rel if f["status"] in COUNTED and f["scope_excluded"]), None)
        out["counted"] = False
        if scoped:
            out["excluded_reason"], out["excluded_detail"] = scoped["scope_excluded"]["code"], scoped["scope_excluded"]["detail"]
            out["excluded_outcome"] = scoped["outcome"]
        else:
            out["excluded_reason"] = ("only_subgroup_or_prognostic" if any(f["subgroup"] for f in rel if f["status"] in COUNTED)
                                      else "relevant_finding_not_verified" if rel else "no_finding_on_asked_outcome")
        return out
    out["counted"] = True
    # weight is reduced if the finding reports no interval/p (direction rests on the model's label alone)
    if "no_uncertainty_reported" in headline["flags"]:
        out["weight"] = round(out["weight"] * 0.6, 3)
        out["weight_parts"]["uncertainty"] = 0.6
    return out


MIN_TIER_STUDIES = 3


def select_tier(studies: list[dict], interp: Interpretation) -> dict:
    """Judge the topic on ONE outcome tier. A tally that mixes LDL cholesterol with myocardial infarction is not a verdict about either.
    The primary tier is the tier of the outcome the question names first (clinical events > validated surrogates > other biomarkers) if it has at
    least MIN_TIER_STUDIES studies with an interpretable result, else the best other tier that does; if none does, the tier with the most such
    studies (ties -> the better tier). Counted studies whose only
    finding is in another tier are set aside with the reason 'other_outcome_tier' and stay visible. Mutates `studies`."""
    counted = [s for s in studies if s.get("counted")]
    per: dict[int, dict] = {}
    for s in counted:
        for t, cid in (s.get("tier_claim_ids") or {}).items():
            f = next(f for f in s["findings"] if f["claim_id"] == cid)
            d = per.setdefault(int(t), {"studies": 0, "informative": 0, "favorable": 0, "null": 0, "unfavorable": 0, "unclear": 0})
            d["studies"] += 1
            d["informative"] += f["stance"] != "unclear"
            d[f["stance"]] += 1
    best = tier_of(interp.outcome_terms[0]) if interp.outcome_terms else 1     # the question's own first-named outcome sets the kind of outcome it asks about
    if not per:
        return {"primary": None, "best_tier": best, "tiers": {}, "label": None, "reason": "no counted studies"}
    order = sorted(per, key=lambda t: (t != best, t))                       # the kind of outcome the question names first, then the best remaining
    enough = [t for t in order if per[t]["informative"] >= MIN_TIER_STUDIES]
    if enough:
        primary = enough[0]
        why = (f"the kind of outcome the question asks about first, with at least {MIN_TIER_STUDIES} interpretable studies" if primary == best
               else f"no studies of the outcome the question names first, or too few; the best other tier with at least {MIN_TIER_STUDIES} interpretable studies")
    else:
        primary = min(per, key=lambda t: (-per[t]["informative"], t))
        why = f"no tier has {MIN_TIER_STUDIES} interpretable studies; the tier with the most was used"
    for s in counted:
        cid = (s.get("tier_claim_ids") or {}).get(str(primary))
        if cid is None:
            s["counted"], s["excluded_reason"] = False, "other_outcome_tier"
            s["excluded_detail"] = "findings only on " + ", ".join(TIER_LABEL[int(t)] for t in sorted(s["tier_claim_ids"])) + f"; the verdict is judged on {TIER_LABEL[primary]}"
        else:
            s["headline"] = next(f for f in s["findings"] if f["claim_id"] == cid)
    return {"primary": primary, "best_tier": best, "label": TIER_LABEL[primary], "reason": why,
            "tiers": {str(t): {**per[t], "label": TIER_LABEL[t]} for t in sorted(per)}}


# ------------------------------------------------------------------------------------------------ comparison
def cluster_outcomes(studies: list[dict]) -> list[dict]:
    clusters: list[dict] = []
    for s in studies:
        if not s.get("counted"):
            continue
        for f in s.get("findings", []):
            if not (f["outcome_relevant"] and f["status"] in COUNTED and not f["subgroup"] and not f.get("scope_excluded")
                    and f.get("tier") == s["headline"].get("tier")):
                continue
            tk = set(tokens(f["outcome"] or ""))
            target = next((c for c in clusters if tk and len(tk & c["tokens"]) / len(tk | c["tokens"]) >= 0.5), None)
            if target is None:
                target = {"label": f["outcome"], "tokens": tk, "members": []}
                clusters.append(target)
            if not any(m["paper_id"] == s["paper_id"] for m in target["members"]):
                target["members"].append({"paper_id": s["paper_id"], "claim_id": f["claim_id"], "stance": f["stance"], "weight": s["weight"],
                                          "measure": f["effect_measure"], "value": f["effect_value"], "lo": f["ci_low"], "hi": f["ci_high"],
                                          "design": s["design"], "n": s["sample_size"]})
    out = []
    for c in sorted(clusters, key=lambda c: -len(c["members"])):
        cnt = defaultdict(int)
        for m in c["members"]:
            cnt[m["stance"]] += 1
        out.append({"label": c["label"], "n": len(c["members"]), "counts": dict(cnt), "members": c["members"]})
    return out


def find_conflicts(counted: list[dict]) -> list[dict]:
    out = []
    for i, a in enumerate(counted):
        for b in counted[i + 1:]:
            ha, hb = a["headline"], b["headline"]
            kind = None
            if {ha["stance"], hb["stance"]} == {"favorable", "unfavorable"}:
                kind = "opposite_directions"
            elif {ha["stance"], hb["stance"]} == {"favorable", "null"} or {ha["stance"], hb["stance"]} == {"unfavorable", "null"}:
                nul = a if ha["stance"] == "null" else b
                if nul["weight"] >= 0.5 and nul["headline"]["precision"] == "precise":
                    kind = "significant_vs_precise_null"
            if not kind:
                continue
            diffs = []
            if a["design"] != b["design"]:
                diffs.append(f"design: {a['design_label']} vs {b['design_label']}")
            if a["sample_size"] and b["sample_size"] and max(a["sample_size"], b["sample_size"]) / max(1, min(a["sample_size"], b["sample_size"])) >= 3:
                diffs.append(f"sample size: {a['sample_size']:,} vs {b['sample_size']:,}")
            for t, lab in (("population", "population"), ("intervention", "intervention"), ("comparator", "comparator"), ("follow_up", "follow-up")):
                if a["pico"].get(t) and b["pico"].get(t) and a["pico"][t].lower() != b["pico"][t].lower():
                    diffs.append(f"{lab} differs")
            out.append({"kind": kind, "a": a["paper_id"], "b": b["paper_id"], "claim_ids": [ha["claim_id"], hb["claim_id"]],
                        "differences": diffs, "score": a["weight"] * b["weight"]})
    out.sort(key=lambda c: -c["score"])
    return out[:6]


def verdict_for(counted: list[dict]) -> dict:
    S = sum(s["weight"] for s in counted if s["headline"]["stance"] == "favorable")
    C = sum(s["weight"] for s in counted if s["headline"]["stance"] == "unfavorable")
    N = sum(s["weight"] for s in counted if s["headline"]["stance"] == "null")
    U = sum(1 for s in counted if s["headline"]["stance"] == "unclear")
    W = S + C + N
    sh = {"supports": S / W if W else 0, "contradicts": C / W if W else 0, "null": N / W if W else 0}
    informative = [s for s in counted if s["headline"]["stance"] != "unclear"]
    nS = sum(1 for s in counted if s["headline"]["stance"] == "favorable")
    nC = sum(1 for s in counted if s["headline"]["stance"] == "unfavorable")
    R = VERDICT_RULES
    if len(informative) < R["min_studies"]:
        label = "Insufficient evidence"
        why = f"Only {len(informative)} counted stud{'y' if len(informative) == 1 else 'ies'} with an interpretable result (minimum {R['min_studies']})."
    elif (sh["supports"] >= R["mixed_if_each_at_least"] and sh["contradicts"] >= R["mixed_if_each_at_least"]
          and nS >= R["mixed_min_studies_each_side"] and nC >= R["mixed_min_studies_each_side"]):
        label, why = "Mixed / conflicting", "Both supporting and contradicting studies carry substantial weight."
    elif sh["supports"] >= R["supported"]:
        label, why = "Supported", "Most of the weighted evidence points the way the question asks."
    elif sh["supports"] >= R["leans"]:
        label, why = "Leans supported", "A plurality of the weighted evidence supports it, with many null results."
    elif sh["contradicts"] >= R["supported"]:
        label, why = "Contradicted", "Most of the weighted evidence points the opposite way."
    elif sh["contradicts"] >= R["leans"]:
        label, why = "Leans contradicted", "A plurality of the weighted evidence points the opposite way."
    else:
        label, why = "No clear effect", "Most counted studies found no statistically significant difference."
    return {"label": label, "why": why, "weights": {"supports": round(S, 3), "contradicts": round(C, 3), "null": round(N, 3)},
            "shares": {k: round(v, 3) for k, v in sh.items()}, "n_informative": len(informative), "n_unclear": U, "n_supports": nS, "n_contradicts": nC, "rules": R}


def _i_squared(counted: list[dict], clusters: list[dict] | None = None) -> tuple[float | None, int, str | None]:
    """Cochran's Q / I^2 over ratio-scale results (HR/RR/OR) with an interval, within the largest outcome cluster that has >= 3 of them
    (mixing mortality, fractures and biomarkers in one statistic would manufacture heterogeneity). Falls back to all headline results
    when no clusters are supplied. Returns (I2, k, outcome label)."""
    def pts_of(rows):
        out = []
        for m in rows:
            v, lo, hi = m.get("value"), m.get("lo"), m.get("hi")
            if m.get("measure") in ("HR", "RR", "OR") and v and v > 0 and lo and hi and lo > 0 and hi > lo:
                out.append((math.log(v), math.log(hi / lo) / (2 * 1.96)))
        return out
    if clusters is not None:
        cands = [(c["label"], pts_of(c["members"])) for c in clusters]
    else:
        cands = [(None, pts_of([{"measure": s["headline"]["effect_measure"], "value": s["headline"]["effect_value"],
                                 "lo": s["headline"]["ci_low"], "hi": s["headline"]["ci_high"]} for s in counted]))]
    label, pts = max(cands, key=lambda x: len(x[1]), default=(None, []))
    if len(pts) < 3:
        return None, len(pts), None
    w = [1 / se ** 2 for _, se in pts]
    ybar = sum(wi * y for wi, (y, _) in zip(w, pts)) / sum(w)
    q = sum(wi * (y - ybar) ** 2 for wi, (y, _) in zip(w, pts))
    df = len(pts) - 1
    return (max(0.0, (q - df) / q) if q > 0 else 0.0), len(pts), label


LEVELS = ["very low", "low", "moderate", "high"]


def certainty_for(counted: list[dict], verdict: dict, conflicts: list[dict], clusters: list[dict] | None = None, tiers: dict | None = None) -> dict:
    """GRADE-inspired, rule-based, deliberately conservative. Steps down from a starting level set by study design.

    start        high if most weight is RCT/meta-analysis, else low
    risk of bias -1 if most weight comes from studies with some/higher concern or not assessable; -2 if most is higher concern
    inconsistency-1 if supporting and opposing (or supporting and many null) results coexist, or ratio estimates are heterogeneous (I^2 >= 50%); -2 if I^2 >= 75%
    imprecision  -1 if pooled N < 400 or half the intervals are wide; -2 if both
    indirectness -1 if 30%+ of studies cover only part of the question
    thin base    -2 if fewer than 5 interpretable studies (3-4 studies can never be rated above 'low')
    cap          never above 'moderate': publication bias cannot be assessed here; 'moderate' at most if most studies were appraised from abstracts only
    """
    n = len(counted)
    if verdict["n_informative"] < VERDICT_RULES["min_studies"]:
        return {"level": "not rated", "start": None, "downgrades": [], "cap": None,
                "note": "Certainty is not rated when there are too few interpretable studies to reach a verdict."}
    wsum = sum(s["weight"] for s in counted) or 1.0
    exp_w = sum(s["weight"] for s in counted if s["design"] in EXPERIMENTAL or s["design"] == "meta_analysis")
    start = "high" if exp_w / wsum >= 0.5 else "low"
    d = []

    # risk of bias, weighted
    w_some = sum(s["weight"] for s in counted if s["rob"] != "lower") / wsum
    w_high = sum(s["weight"] for s in counted if s["rob"] == "higher") / wsum
    n_assess = sum(1 for s in counted if s["rob"] != "not_assessable")
    steps = 2 if w_high >= 0.5 else 1 if w_some >= 0.5 else 0
    d.append({"domain": "risk of bias", "steps": steps, "applied": bool(steps),
              "reason": f"{w_some:.0%} of the weight is from studies with some concern, higher concern or unassessable bias; {n_assess} of {n} could be screened"})

    # inconsistency
    sh = verdict["shares"]
    i2, k, olabel = _i_squared(counted, clusters)
    stance_conflict = (sh["supports"] >= 0.2 and (sh["contradicts"] >= 0.2 or sh["null"] >= 0.3)) or (sh["contradicts"] >= 0.2 and sh["null"] >= 0.3) \
        or any(c["kind"] == "opposite_directions" for c in conflicts)
    steps = 2 if (i2 is not None and i2 >= 0.75) else 1 if (stance_conflict or (i2 is not None and i2 >= 0.5)) else 0
    bits = []
    if i2 is not None:
        bits.append(f"I² = {i2:.0%} across {k} ratio estimates" + (f" for “{olabel}”" if olabel else ""))
    bits.append("supporting, null and/or opposing results coexist" if stance_conflict
                else "estimates differ in size though they point the same way" if (i2 is not None and i2 >= 0.5) else "results agree in direction")
    d.append({"domain": "inconsistency", "steps": steps, "applied": bool(steps), "reason": "; ".join(bits)})

    # imprecision
    total_n = sum(s["sample_size"] or 0 for s in counted)
    ratio = [s for s in counted if s["headline"]["precision"] != "unclassified"]
    wide = bool(ratio) and sum(1 for s in ratio if s["headline"]["precision"] == "imprecise") >= 0.5 * len(ratio)
    small = total_n < 400
    steps = int(small) + int(wide)
    d.append({"domain": "imprecision", "steps": steps, "applied": bool(steps),
              "reason": f"pooled sample {total_n:,}{' (< 400)' if small else ''}; " + ("half or more of the intervals are wide" if wide else "intervals mostly narrow")})

    # indirectness
    indirect = sum(1 for s in counted if s["relevance"] < 1)
    d.append({"domain": "indirectness", "steps": int(indirect >= 0.3 * n), "applied": indirect >= 0.3 * n,
              "reason": f"{indirect} of {n} studies cover only part of the question" if indirect else "all counted studies cover every concept in the question"})

    # indirect outcome: the verdict rests on a surrogate although the question asks about clinical events
    if tiers and tiers.get("primary") and tiers["primary"] > tiers.get("best_tier", 1):
        d.append({"domain": "surrogate outcomes", "steps": 1, "applied": True,
                  "reason": f"the verdict rests on {TIER_LABEL[tiers['primary']]}, a lesser kind of outcome than the question asks about ({TIER_LABEL[tiers.get('best_tier', 1)]})"})

    # thin evidence base
    thin = verdict["n_informative"] < 5
    d.append({"domain": "evidence base", "steps": 2 if thin else 0, "applied": thin,
              "reason": f"only {verdict['n_informative']} interpretable studies (fewer than 5)" if thin else f"{verdict['n_informative']} interpretable studies"})

    level = LEVELS.index(start) - sum(x["steps"] for x in d)
    cap, cap_why = "moderate", "publication bias cannot be assessed here, so certainty is never rated higher than moderate"
    abstract_share = sum(1 for s in counted if s["basis"] == "abstract") / n
    if abstract_share > 0.5:
        cap_why += f"; {abstract_share:.0%} of studies were appraised from the abstract only"
    level = max(0, min(level, LEVELS.index(cap)))
    return {"level": LEVELS[level], "start": start, "downgrades": d, "cap": cap_why,
            "note": "GRADE-inspired screen from the text of the papers; it does not replace a formal GRADE assessment or systematic review."}


# ------------------------------------------------------------------------------------------------ statements
def short(s: dict) -> str:
    t = (s.get("title") or "").rstrip(". ")
    t = t if len(t) <= 70 else t[:67].rsplit(" ", 1)[0] + "…"
    return f"“{t}” ({s['journal'] or 'journal n/a'} {s['year'] or ''}, PMID {s['pmid']})".replace("  ", " ")


STANCE_PHRASE = {"favorable": "in the direction the question asks about (statistically significant)",
                 "unfavorable": "in the opposite direction to the question (statistically significant)",
                 "null": "with no statistically significant difference", "unclear": "with an unclear direction"}


def build_statements(interp, counted, verdict, conflicts, by_id) -> list[dict]:
    st = []
    n = len(counted)
    cnt = defaultdict(list)
    for s in counted:
        cnt[s["headline"]["stance"]].append(s)
    all_ids = [s["headline"]["claim_id"] for s in counted]
    if n:
        st.append({"id": "headline", "kind": "headline",
                   "text": (f"Of {n} counted stud{'y' if n == 1 else 'ies'}, {len(cnt['favorable'])} report a significant effect in the direction the question asks about, "
                            f"{len(cnt['null'])} report no significant difference, {len(cnt['unfavorable'])} report a significant effect in the opposite direction"
                            + (f", and {len(cnt['unclear'])} have an unclear direction." if cnt["unclear"] else ".")),
                   "claim_ids": all_ids, "requires_citation": True})
        st.append({"id": "verdict", "kind": "verdict", "text": f"{verdict['label']}. {verdict['why']}", "claim_ids": all_ids, "requires_citation": True})
    for s in sorted(counted, key=lambda s: -s["weight"]):
        h = s["headline"]
        st.append({"id": f"study-{s['paper_id']}", "kind": "study", "paper_id": s["paper_id"], "claim_ids": [h["claim_id"]], "requires_citation": True,
                   "text": f"{short(s)}, {s['design_label']}{', N = ' + format(s['sample_size'], ',') if s['sample_size'] else ''}: {h['outcome']} - "
                           f"{h['estimate'] or 'no estimate reported'}, {STANCE_PHRASE[h['stance']]}."})
    for i, c in enumerate(conflicts):
        a, b = by_id[c["a"]], by_id[c["b"]]
        why = "; ".join(c["differences"]) or "no obvious difference in design, size or PICO was extracted"
        st.append({"id": f"conflict-{i}", "kind": "conflict", "claim_ids": c["claim_ids"], "requires_citation": True,
                   "text": f"{short(a)} and {short(b)} point in different directions ({c['kind'].replace('_', ' ')}). Differences: {why}."})
    ab = [s for s in counted if s["basis"] == "abstract"]
    st.append({"id": "caveat-basis", "kind": "caveat", "claim_ids": [], "requires_citation": False,
               "text": f"{len(ab)} of {n} counted studies were appraised from the abstract only, where missing safeguards are 'not assessable' rather than absent."})
    return st
