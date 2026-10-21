"""Claim battery against the real corpus (skipped when the dev database is empty). Each case pins behaviour found worth pinning while testing
diverse claims: out-of-corpus claims must come back 'Insufficient evidence' with nothing counted; polarity must follow the claim's wording;
sodium-glucose cotransporter papers must never be counted as salt evidence; cause-specific mortality must not answer an all-cause question."""
import pytest

from app.db import connect
from app.synthesis.report import build_report

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def conn():
    try:
        c = connect()
        n = c.execute("SELECT count(*) n FROM claims").fetchone()["n"]
    except Exception:
        pytest.skip("no dev database")
    if n < 500:
        pytest.skip("dev corpus not loaded")
    yield c
    c.close()


def run(conn, q):
    return build_report(conn, q, refresh=True)


@pytest.mark.parametrize("q", [
    "Does exercise reduce depression?", "Do statins reduce cardiovascular mortality?", "Does vitamin C prevent the common cold?",
    "Does garlic lower blood pressure?", "Does meditation reduce anxiety?"])
def test_out_of_corpus_claims_count_nothing(conn, q):
    r = run(conn, q)
    assert r["counts"]["counted"] == 0 and r["verdict"]["label"] == "Insufficient evidence" and r["certainty"]["level"] == "not rated"


@pytest.mark.parametrize("q,pol", [
    ("Does vitamin D increase mortality?", "harm"), ("Is ultra-processed food consumption linked to higher mortality?", "harm"),
    ("Does eating more ultra-processed food increase obesity risk?", "harm"), ("Does intermittent fasting cause more weight loss than calorie restriction?", "benefit"),
    ("Does reducing salt intake lower blood pressure?", "benefit"), ("Is intermittent fasting dangerous?", "harm")])
def test_polarity_follows_wording(conn, q, pol):
    assert run(conn, q)["interpretation"]["polarity"] == pol


@pytest.mark.parametrize("q", ["Does reducing salt intake lower blood pressure?", "Do salt substitutes reduce blood pressure?", "Does a low sodium diet reduce cardiovascular events?"])
def test_sodium_glucose_drug_papers_are_never_salt_evidence(conn, q):
    r = run(conn, q)
    assert not [s for s in r["studies"] if s["counted"] and ("cotransporter" in s["title"].lower() or "sglt" in s["title"].lower() or "gliflozin" in s["title"].lower())]


def test_salt_and_blood_pressure_is_answered_from_sbp_findings(conn):
    r = run(conn, "Does reducing salt intake lower blood pressure?")
    assert r["counts"]["counted"] >= 5 and r["verdict"]["label"] in ("Supported", "Leans supported", "Mixed / conflicting")


def test_all_cause_mortality_question_rejects_cause_specific_outcomes(conn):
    r = run(conn, "Does the Mediterranean diet reduce all-cause mortality?")
    for s in r["studies"]:
        if s["counted"]:
            o = s["headline"]["outcome"].lower()
            assert not any(q in o for q in ("cardiovascular", "cancer", "stroke", "neonatal")), o


def test_harm_claim_about_a_protective_exposure_is_not_supported(conn):
    r = run(conn, "Does vitamin D increase mortality?")
    assert r["verdict"]["label"] not in ("Supported", "Leans supported")


@pytest.mark.parametrize("q", [
    "Does vitamin D supplementation reduce the risk of hip fractures?", "Does time-restricted eating improve glycaemic control?", "Does empagliflozin improve outcomes in heart failure?",
    "Do SGLT2 inhibitors reduce hospitalization for heart failure?", "Vitamin D and fractures"])
def test_every_answer_passes_its_own_citation_audit(conn, q):
    r = run(conn, q)
    assert r["audit"]["failed"] == 0 and not r["withheld"]


@pytest.mark.parametrize("q,pol", [("processed foods are unhealthy", "harm"), ("Is red meat bad for your health?", "harm"), ("Are nuts good for you?", "benefit"),
                                   ("Is saturated fat bad for the heart?", "harm"), ("Is a vegetarian diet healthier?", "benefit"), ("Is coffee healthy?", "benefit")])
def test_vague_health_claims_are_parsed_with_exposure_and_polarity(conn, q, pol):
    i = run(conn, q)["interpretation"]
    assert i["polarity"] == pol and i["polarity_source"] == "parsed"
    assert i["exposure_terms"] or i["source"] == "preset"      # rules found too few studies -> the claim was routed to its preset topic (alias)


def test_processed_foods_claim_counts_ultra_processed_food_studies_only(conn):
    r = run(conn, "processed foods are unhealthy")
    counted = [s for s in r["studies"] if s["counted"]]
    assert len(counted) >= 4 and r["verdict"]["label"] in ("Supported", "Leans supported")
    assert all("process" in (s["title"] + " " + str(s["pico"].get("intervention"))).lower() for s in counted)


def test_substitution_analyses_are_read_as_less_red_meat(conn):
    """'Replacing red meat with white meat' is evidence about LESS red meat: it is counted, but only with the direction normalised accordingly
    (a benefit of the replacement supports 'red meat is bad'). Before pipeline v4 these were excluded wholesale or, worse, mis-signed."""
    r = run(conn, "Is red meat bad for your health?")
    repl = [s for s in r["studies"] if s["counted"] and "replac" in s["headline"]["outcome"].lower()]
    for s in repl:
        h = s["headline"]
        assert h["orientation"]["exposure_less"] is True, h["outcome"]
        assert (h["direction"] == "favors_intervention") == (h["stance"] == "favorable"), h["outcome"]


def test_saturated_fat_reduction_trials_are_read_in_the_right_direction(conn):
    r = run(conn, "Is saturated fat bad for the heart?")
    assert r["verdict"]["label"] not in ("Contradicted", "Leans contradicted")      # reduction trials favoring the intervention SUPPORT 'saturated fat is bad'


@pytest.mark.parametrize("q", ["Does fiber lower the risk of heart disease?", "Do omega-3 supplements reduce heart disease?"])
def test_heart_disease_matches_cardiovascular_outcomes(conn, q):
    assert run(conn, q)["counts"]["counted"] >= 2


@pytest.mark.parametrize("q", ["Vitamin D helps with bone strength", "Is vitamin D good for your bones?"])
def test_vague_bone_claims_are_counted_against_fractures_and_bone_density(conn, q):
    r = run(conn, q)
    assert {"fractures", "bone mineral density"} <= set(r["interpretation"]["outcome_terms"])
    assert r["counts"]["counted"] >= 3 and r["audit"]["failed"] == 0


def test_vitamin_d_is_not_any_vitamin(conn):
    r = run(conn, "vitamin B12 improves memory")
    assert r["counts"]["counted"] == 0
