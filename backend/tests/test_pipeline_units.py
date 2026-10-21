"""Unit tests (no database) for the v4 evidence-pipeline fixes: outcome head/tier matching, exposure orientation, scope exclusions,
single-tier verdicts and the 'Mixed' rule."""
import json
from pathlib import Path

import pytest

from app.synthesis.interpret import interpret
from app.synthesis.outcomes import match_outcome, outcome_head, tier_of
from app.synthesis.scope import Exposure, exposure_less, scope_exclusion
from app.synthesis.synthesize import ENGINE_VERSION, VERDICT_RULES, exposure_matches, select_tier, verdict_for

QS = {q["slug"]: q["question"] for q in json.loads((Path(__file__).parent.parent / "data" / "questions.json").read_text())}


def interp(slug):
    return interpret(QS[slug])


# ---------------------------------------------------------------- outcome head / tier
@pytest.mark.parametrize("outcome,head", [
    ("IBD onset, high cholesterol intake", "IBD onset"),
    ("LDL cholesterol, higher vs lower P:S ratio diets", "LDL cholesterol"),
    ("Between-group difference in change in 24-h systolic BP at 24 weeks", "24-h systolic BP"),
    ("difference in weight change between 5:2 IF and CCR at 12 weeks", "weight change"),
    ("Correlation of daily sodium intake with systolic blood pressure", "systolic blood pressure"),
])
def test_outcome_head(outcome, head):
    assert outcome_head(outcome) == head


def test_related_compounds_do_not_leak_the_exposure_into_the_head():
    assert "obesity" not in outcome_head("Non-obesity-related cancer").lower()


def test_exposure_words_after_the_head_are_not_outcomes():
    sat = interp("sat-fat")
    assert not match_outcome("IBD onset, high cholesterol intake", sat.outcome_terms)[0]
    assert not match_outcome("GDM risk, higher dietary cholesterol intake", sat.outcome_terms)[0]
    assert not match_outcome("High waist circumference, highest vs lowest dietary cholesterol", sat.outcome_terms)[0]
    assert match_outcome("Myocardial infarction, per 100-mg/d dietary cholesterol", sat.outcome_terms)[0]      # same outcome class as 'cardiovascular'
    assert not match_outcome("Insulin change, LCD only at follow-up (without diabetes)", ["diabetes"])[0]


def test_cause_or_setting_specific_mortality_does_not_answer_all_cause():
    vd = interp("vitd")
    assert match_outcome("All-cause mortality", vd.outcome_terms)[0]
    assert not match_outcome("Neonatal mortality", vd.outcome_terms)[0]
    assert not match_outcome("lung cancer-specific mortality", interp("sat-fat").outcome_terms)[0]


@pytest.mark.parametrize("head,tier", [("All-cause mortality", 1), ("Myocardial infarction", 1), ("LDL cholesterol", 2), ("Systolic BP", 2),
                                       ("Body weight", 2), ("HbA1c", 2), ("Fasting glucose", 3), ("Blood NAD+", 3), ("Cardiac function", 3)])
def test_tiers(head, tier):
    assert tier_of(head) == tier


def test_a_lesser_outcome_than_any_the_question_names_is_not_matched_by_class():
    assert not match_outcome("Cardiac function (LV diameters)", interp("sglt2-hf").outcome_terms)[0]


# ---------------------------------------------------------------- orientation
def less(slug, outcome, interv, comp=""):
    return exposure_less(Exposure(interp(slug)), outcome, interv, comp)[0]


def test_composition_and_replacement_wording_means_less_of_the_exposure():
    assert less("sat-fat", "LDL cholesterol, higher vs lower P:S ratio diets", "higher P:S ratio diets", "lower P:S ratio diets") is True
    assert less("sat-fat", "LDL cholesterol, higher vs lower P:S ratio", "") is True
    assert less("red-meat", "Liver cancer, replacing red meat with white meat", "replacing red meat with white meat") is True
    assert less("sweeteners", "Weight change", "replacing daily caloric sugars with NNS") is False        # the exposure is what is introduced


def test_exposure_in_the_comparator_arm_flips_the_orientation():
    assert less("sat-fat", "Total cholesterol increase with butter", "extra virgin olive oil", "butter") is True


def test_reduction_words_must_attach_to_the_exposure():
    assert less("sodium", "SBP change", "low-sodium diet", "usual diet") is True
    assert less("sodium", "SBP change", "salt substitute", "regular salt") is True
    assert less("plant-based", "Body weight", "low-fat vegan diet") is False                  # 'low-fat' reduces fat, not the plant-based exposure
    assert less("low-carb", "BMI", "very-low-calorie ketogenic diet", "low-calorie diet") is False
    assert less("fiber", "Triglycerides", "whole-grain staple replacement at 100 g/day", "control") is False
    assert less("sat-fat", "All-cause mortality, highest vs lowest quintile saturated fat", "highest quintile of saturated fat intake") is False


# ---------------------------------------------------------------- exposure / scope
def test_look_alike_exposures_are_not_the_exposure():
    pico = lambda i, c="": {"intervention": i, "comparator": c}
    assert not exposure_matches(interp("red-meat"), "Meat intake and mortality", pico("higher unprocessed poultry intake"), "cohort")[0]
    assert not exposure_matches(interp("ssb"), "Non-sugar-sweetened beverages", pico("non-sugar-sweetened beverage intake"), "meta_analysis")[0]
    assert not exposure_matches(interp("plant-based"), "Butter and plant-based oils intake", pico("highest intake of butter or plant-based oils"), "cohort")[0]
    assert not exposure_matches(interp("fruit-veg"), "Preserved vegetable consumption", pico("preserved vegetable consumption"), "cohort")[0]
    assert exposure_matches(interp("red-meat"), "Red meat and diabetes", pico("highest quintile of red meat consumption"), "cohort")[0]


def test_scope_exclusions_carry_a_reason():
    sat, vd = interp("sat-fat"), interp("vitd")
    r = scope_exclusion(sat, "Dietary fat and mortality among patients with prostate cancer", {"population": "patients with nonmetastatic prostate cancer"}, "All-cause mortality")
    assert r and r[0] == "population_out_of_scope" and r[1]
    assert scope_exclusion(vd, "Vitamin D in sepsis", {"population": "patients with sepsis"}, "28-day mortality")[0] == "population_out_of_scope"
    assert scope_exclusion(vd, "Vitamin D in pregnancy", {"population": "pregnant women"}, "Neonatal mortality")[0] == "population_out_of_scope"
    assert scope_exclusion(interp("ssb"), "City-level sugar-sweetened beverage taxes and BMI", {"intervention": "city-level SSB excise taxes"}, "BMI")[0] == "study_type_out_of_scope"
    assert scope_exclusion(sat, "Dietary cholesterol and myocardial infarction", {"population": "veterans"}, "Myocardial infarction") is None
    assert scope_exclusion(interp("coffee"), "Coffee and cancer patients' survival", {"population": "cancer patients"}, "Cancer progression")[0] == "population_out_of_scope"


# ---------------------------------------------------------------- tiers, verdict
def study(pid, tier, stance, weight=0.5):
    f = {"claim_id": pid * 10 + tier, "tier": tier, "stance": stance}
    return {"paper_id": pid, "counted": True, "weight": weight, "findings": [f], "headline": f, "tier_claim_ids": {str(tier): f["claim_id"]}}


def test_one_tier_per_verdict_and_other_tiers_are_set_aside_visibly():
    sat = interp("sat-fat")
    studies = [study(1, 1, "favorable"), study(2, 1, "null"), study(3, 1, "favorable"), study(4, 2, "unfavorable"), study(5, 2, "favorable")]
    t = select_tier(studies, sat)
    assert t["primary"] == 1
    assert [s["paper_id"] for s in studies if s["counted"]] == [1, 2, 3]
    assert all(s["excluded_reason"] == "other_outcome_tier" and s["excluded_detail"] for s in studies if not s["counted"])
    assert t["tiers"]["2"]["informative"] == 2                                   # still reported


def test_the_tier_the_question_names_first_is_used_when_it_has_enough_studies():
    dash = interp("dash")                                                        # 'blood pressure' first -> tier 2
    studies = [study(i, 1, "favorable") for i in range(1, 5)] + [study(i, 2, "favorable") for i in range(5, 9)]
    assert select_tier(studies, dash)["primary"] == 2


def test_mixed_needs_two_studies_on_each_side():
    one_dissent = [study(1, 1, "favorable", .5), study(2, 1, "favorable", .5), study(3, 1, "favorable", .5), study(4, 1, "unfavorable", .4)]
    v = verdict_for(one_dissent)
    assert v["shares"]["contradicts"] >= VERDICT_RULES["mixed_if_each_at_least"] and v["label"] != "Mixed / conflicting"
    two = one_dissent + [study(5, 1, "unfavorable", .4)]
    assert verdict_for(two)["label"] == "Mixed / conflicting"


def test_cache_key_changes_with_pipeline_version():
    assert ENGINE_VERSION == "4"
