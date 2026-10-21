"""Study appraisal, stance relative to the question, verdict thresholds, claim status."""
import pytest

from app.claims.materialize import claim_status, numeric_matches
from app.synthesis.assess import finding_stats, rob_level, screen_signals, size_weight
from app.synthesis.interpret import interpret
from app.synthesis.synthesize import (certainty_for, exposure_matches, outcome_matches, stance_of, verdict_for)


def f(measure="HR", ev=0.8, lo=0.7, hi=0.9, p=None, d="favors_intervention"):
    return {"effect_measure": measure, "effect_value": ev, "ci_low": lo, "ci_high": hi, "p_value": p, "direction": d}


# ---- statistical uncertainty
def test_ratio_interval_decides_significance():
    assert finding_stats(f()).significant is True
    assert finding_stats(f(ev=0.86, lo=0.68, hi=1.08)).significant is False


def test_mean_difference_null_is_zero():
    assert finding_stats(f("MD", -2, -4, -1)).significant is True
    assert finding_stats(f("MD", -0.2, -1.2, 0.8)).significant is False


def test_p_ci_disagreement_is_flagged_not_hidden():
    s = finding_stats(f(p=1.0))                       # CI excludes 1 but p = 1: an extraction error to surface
    assert "p_value_and_ci_disagree" in s.flags and s.significant is True


def test_no_interval_no_p_means_unknown():
    s = finding_stats(f(ev=0.9, lo=None, hi=None))
    assert s.significant is None and "no_uncertainty_reported" in s.flags


def test_precision_label_uses_log_width():
    assert finding_stats(f(ev=0.8, lo=0.75, hi=0.85)).precision == "precise"
    assert finding_stats(f(ev=0.8, lo=0.3, hi=2.1)).precision == "imprecise"


# ---- stance relative to what is asked
def test_stance_depends_on_polarity():
    sig_good = f(d="favors_intervention")
    assert stance_of(sig_good, finding_stats(sig_good), "benefit")[:2] == ("favorable", "supports")
    assert stance_of(sig_good, finding_stats(sig_good), "harm")[:2] == ("unfavorable", "contradicts")


def test_interval_overrides_a_direction_label():
    x = f(ev=0.86, lo=0.68, hi=1.08, d="favors_intervention")
    stance, role, flags = stance_of(x, finding_stats(x), "benefit")
    assert (stance, role) == ("null", "contextualizes") and "direction_label_overridden_by_interval" in flags


def test_unclear_direction_never_supports():
    x = f(d="unclear")
    assert stance_of(x, finding_stats(x), "benefit")[0] == "unclear"


# ---- bias screen: absence from an abstract is not evidence of absence
PASS = lambda t, kind="pubmed_abstract", sec="methods": {"uid": "u", "text": t, "section": sec, "doc_kind": kind}


def test_abstract_only_marks_missing_safeguards_not_assessable():
    sig = {s.key: s for s in screen_signals("rct", [PASS("A randomized trial of X.")], has_fulltext=False)}
    assert sig["randomization"].status == "present" and sig["concealment"].status == "not_assessable"
    assert rob_level("rct", list(sig.values()))[0] in ("some", "not_assessable")


def test_fulltext_marks_missing_safeguards_absent():
    sig = {s.key: s for s in screen_signals("rct", [PASS("We randomized patients.", "pmc_jats")], has_fulltext=True)}
    assert sig["concealment"].status == "absent" and sig["blinding"].status == "absent"
    assert rob_level("rct", list(sig.values()))[0] == "higher"


def test_well_reported_rct_screens_lower():
    txt = "Participants were randomized centrally using an IWRS; double-blind placebo; intention-to-treat; NCT01234567; 5 were lost to follow-up."
    sig = screen_signals("rct", [PASS(txt, "pmc_jats")], has_fulltext=True)
    assert rob_level("rct", sig)[0] == "lower"


def test_size_weight_monotone():
    ws = [size_weight(n)[0] for n in (10, 80, 200, 800, 5000)]
    assert ws == sorted(ws) and size_weight(None)[1] == "unknown"


# ---- verdict
def study(stance, weight=1.0, design="rct", rob="lower", prec="precise", n=500, rel=1.0):
    return {"weight": weight, "design": design, "rob": rob, "sample_size": n, "relevance": rel, "basis": "fulltext",
            "headline": {"stance": stance, "precision": prec, "se": None, "effect_value": None, "effect_measure": None, "ci_low": None, "ci_high": None}}


def test_verdict_needs_three_interpretable_studies():
    assert verdict_for([study("favorable"), study("favorable")])["label"] == "Insufficient evidence"


def test_verdict_labels():
    v = lambda *s: verdict_for(list(s))["label"]
    assert v(*[study("favorable")] * 4) == "Supported"
    assert v(*[study("unfavorable")] * 4) == "Contradicted"
    assert v(*[study("favorable")] * 2, *[study("unfavorable")] * 2) == "Mixed / conflicting"
    assert v(study("favorable"), *[study("null")] * 3) == "No clear effect"
    assert v(*[study("favorable")] * 3, *[study("null")] * 2) == "Leans supported"


def test_weight_matters_not_just_counts():
    assert verdict_for([study("favorable", 1.0), study("null", 0.1), study("null", 0.1), study("null", 0.1)])["label"] == "Supported"


def test_certainty_is_not_rated_without_a_verdict_and_downgrades_for_conflict():
    few = [study("favorable")]
    assert certainty_for(few, verdict_for(few), [])["level"] == "not rated"
    mixed = [study("favorable")] * 2 + [study("unfavorable")] * 2
    c = certainty_for(mixed, verdict_for(mixed), [])
    assert c["start"] == "high" and any(d["domain"] == "inconsistency" and d["applied"] for d in c["downgrades"])
    assert c["level"] in ("low", "very low")


def test_certainty_is_capped_at_moderate_and_thin_evidence_is_downgraded():
    ok = [study("favorable", n=2000) for _ in range(6)]          # consistent, precise, large, full text, low bias
    c = certainty_for(ok, verdict_for(ok), [])
    assert c["level"] == "moderate" and c["cap"]                   # high is never awarded: publication bias is not assessed
    thin = [study("favorable", n=2000) for _ in range(3)]
    t = certainty_for(thin, verdict_for(thin), [])
    assert t["level"] == "low" and any(d["domain"] == "evidence base" and d["applied"] for d in t["downgrades"])


def test_heterogeneous_ratio_estimates_downgrade_inconsistency():
    import math
    def r(v, se=0.05):
        s = study("favorable", n=2000)
        s["headline"].update(effect_value=v, se=se, effect_measure="HR", ci_low=v * math.exp(-1.96 * se), ci_high=v * math.exp(1.96 * se))
        return s
    het = [r(0.5), r(1.0), r(1.6), r(0.7), r(1.3)]
    inc = next(d for d in certainty_for(het, verdict_for(het), [])["downgrades"] if d["domain"] == "inconsistency")
    assert inc["applied"] and "I²" in inc["reason"]
    same = [r(0.8) for _ in range(5)]
    assert not next(d for d in certainty_for(same, verdict_for(same), [])["downgrades"] if d["domain"] == "inconsistency")["applied"]


# ---- topic selection
def test_exposure_must_be_studied_not_just_mentioned():
    it = interpret("Do SGLT2 inhibitors reduce heart-failure hospitalization or cardiovascular death in adults with heart failure?")
    assert it.source == "preset"
    assert exposure_matches(it, "Dapagliflozin in acute heart failure", {}) == (True, None)
    assert exposure_matches(it, "Safety of levosimendan", {"intervention": "levosimendan plus dapagliflozin"}) == (False, "exposure_only_part_of_combination")
    assert exposure_matches(it, "Levosimendan trial", {"intervention": "levosimendan"}) == (False, "exposure_not_studied")


def test_outcome_matching_is_specific():
    terms = interpret("Do SGLT2 inhibitors reduce heart-failure hospitalization or cardiovascular death in adults with heart failure?").outcome_terms
    assert outcome_matches("Cardiovascular death or worsening HF (primary composite)", terms)
    assert not outcome_matches("Kidney-specific composite (eGFR decline, renal death)", terms)
    assert not outcome_matches("HbA1c change", terms)


def test_freetext_question_polarity_is_parsed_and_overridable():
    assert interpret("Does coffee increase the risk of arrhythmia?").polarity == "harm"
    assert interpret("Does exercise reduce depression?").polarity == "benefit"
    q = interpret("Is coffee related to arrhythmia?")
    assert q.polarity_source == "assumed" and q.notes
    assert interpret("Is coffee related to arrhythmia?", "harm").polarity_source == "override"


# ---- claim status and numeric corroboration
def test_claim_status_rules():
    assert claim_status("exact", [])[0] == "verified"
    assert claim_status("exact", ["section_mismatch(claimed=METHODS)"])[0] == "verified"
    assert claim_status("fuzzy", [])[0] == "needs_review"
    assert claim_status("failed", ["quote_not_in_source"])[0] == "unsupported"
    assert claim_status("failed", ["missing_quote"])[0] == "unsupported"
    assert claim_status("failed", ["number_not_in_quote:effect_value"])[0] == "needs_review"
    assert claim_status("exact", ["sanity:ci_excludes_estimate"])[0] == "needs_review"


def test_numeric_match_needs_estimate_and_interval_in_one_segment():
    ps = [{"id": 1, "kind": "paragraph", "text": "HR 0.74 (95% CI 0.63-0.88). In a separate sentence, 0.50 appears."},
          {"id": 2, "kind": "paragraph", "text": "The value 0.74 is mentioned. Elsewhere the interval is 0.63 to 0.88."},
          {"id": 3, "kind": "abstract_section", "text": "HR 0.74 (95% CI 0.63-0.88)"}]
    hits = numeric_matches({"effect_value": 0.74, "ci_low": 0.63, "ci_high": 0.88, "p_value": None}, ps)
    assert [h[0]["id"] for h in hits] == [1]               # not split across sentences, not the abstract itself
    p, a, b = hits[0]
    assert p["text"][a:b].startswith("HR 0.74")


# ---- free-text questions: exposure must be studied, not just mentioned
def test_freetext_splits_exposure_from_outcome_and_first_verb_sets_polarity():
    i = interpret("Do omega-3 or fish oil supplements reduce the risk of fractures in older adults?")
    assert "fish" in i.exposure_terms and "fractures" in i.outcome_terms and i.polarity == "benefit"
    assert "supplements" not in i.exposure_terms
    assert interpret("Does coffee increase the risk of arrhythmia?").polarity == "harm"
    assert interpret("Is coffee a thing").exposure_terms == []


def test_freetext_exposure_check_uses_title_or_intervention():
    i = interpret("Does vitamin D reduce fractures in elderly women?")
    assert exposure_matches(i, "Vitamin D and fracture prevention", {}) == (True, None)
    assert exposure_matches(i, "Calcium and fractures", {"intervention": "calcium"}) == (False, "exposure_not_studied")
    assert exposure_matches(i, "Exercise trial", {"intervention": "vitamin D3 800 IU"}) == (True, None)


# ---- vague health claims
def test_vague_health_claims_become_a_polarity_plus_broad_outcomes():
    for q, pol in [("processed foods are unhealthy", "harm"), ("Are processed foods bad for you?", "harm"), ("Is red meat bad for your health?", "harm"),
                   ("Are nuts good for you?", "benefit"), ("Is coffee healthy?", "benefit"), ("Is sugar harmful?", "harm")]:
        i = interpret(q)
        assert i.polarity == pol and i.polarity_source == "parsed", q
        assert {"mortality", "cardiovascular", "cancer"} <= set(i.outcome_terms) and i.exposure_terms, q
    assert {"ultra-process"} <= set(interpret("processed foods are unhealthy").exposure_terms)       # alias: 'processed food' covers ultra-processed
    assert "bad" not in interpret("Is red meat bad for your health?").exposure_terms


def test_health_claim_pattern_does_not_swallow_ordinary_questions():
    assert interpret("Does coffee increase the risk of arrhythmia?").outcome_terms == ["arrhythmia"]
    assert interpret("Is intermittent fasting dangerous?").polarity == "harm"


# ---- direction normalisation: a trial that REDUCES the exposure
def test_reduction_trial_supports_a_harm_claim_about_the_exposure():
    good = f(d="favors_intervention")                       # the arm that cut the exposure did better
    assert stance_of(good, finding_stats(good), "harm", exposure_less=False, paper_less=True)[0] == "favorable"      # 'more X is bad'
    assert stance_of(good, finding_stats(good), "harm", exposure_less=False, paper_less=False)[0] == "unfavorable"   # a trial ADDING X that did better


def test_claim_about_reducing_the_exposure_agrees_with_cohort_of_high_intake():
    harm_of_high = f(d="favors_comparator")                 # high intake did worse
    assert stance_of(harm_of_high, finding_stats(harm_of_high), "benefit", exposure_less=True, paper_less=False)[0] == "favorable"
    cut_trial = f(d="favors_intervention")
    assert stance_of(cut_trial, finding_stats(cut_trial), "benefit", exposure_less=True, paper_less=True)[0] == "favorable"


def test_low_means_less_only_for_nutrients_not_for_named_diets():
    from app.synthesis.interpret import exposure_is_less
    assert exposure_is_less("a low sodium diet") and exposure_is_less("reducing salt") and exposure_is_less("low-sugar diet")
    assert not exposure_is_less("low carb diets") and not exposure_is_less("ketogenic diets") and not exposure_is_less("time-restricted eating")
