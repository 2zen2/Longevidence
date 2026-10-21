"""Regression test against backend/data/gold/pipeline_gold.json: ~90 studies hand-labelled (NOT expert-labelled; see the file's _readme) for scope,
outcome tier and stance. Each topic's report is rebuilt from the dev database (skipped when the corpus is not loaded)."""
import json
from pathlib import Path

import pytest

from app.db import connect
from app.synthesis.report import build_report

pytestmark = pytest.mark.db

GOLD = json.loads((Path(__file__).parent.parent / "data" / "gold" / "pipeline_gold.json").read_text())
QUESTIONS = {q["slug"]: q["question"] for q in json.loads((Path(__file__).parent.parent / "data" / "questions.json").read_text())}
NOT_IN_SCOPE_REASONS = {"exposure_not_studied", "exposure_only_part_of_combination", "population_out_of_scope", "study_type_out_of_scope", "not_extracted"}


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


@pytest.fixture(scope="module")
def reports(conn):
    cache = {}

    def get(topic):
        if topic not in cache:
            cache[topic] = build_report(conn, QUESTIONS[topic], refresh=True)
        return cache[topic]
    return get


def _params():
    for g in GOLD["labels"]:
        marks = []
        if g.get("known_miss"):
            marks.append(pytest.mark.xfail(reason=g["known_miss"], strict=False))
        yield pytest.param(g, id=f"{g['topic']}-{g['paper_id']}", marks=marks)


@pytest.mark.parametrize("g", list(_params()))
def test_gold_label(reports, g):
    if g["confidence"] != "clear":
        pytest.skip("uncertain label: recorded, not asserted")
    r = reports(g["topic"])
    s = next((x for x in r["studies"] if x["paper_id"] == g["paper_id"]), None)
    if not g["in_scope"]:
        if s is None:
            return                                             # not even retrieved: also fine
        assert not s["counted"], f"{g['why']} (counted instead; headline: {s['headline']['outcome']})"
        assert s.get("excluded_reason") != "other_outcome_tier", f"should be out of scope, not merely another tier: {g['why']}"
        return
    assert s is not None, "in-scope study was not retrieved"
    assert s.get("excluded_reason") not in NOT_IN_SCOPE_REASONS, f"wrongly excluded as {s.get('excluded_reason')}: {s.get('excluded_detail')}"
    cid = (s.get("tier_claim_ids") or {}).get(str(g["tier"]))
    assert cid is not None, f"no finding recognised at tier {g['tier']}; tiers present: {list((s.get('tier_claim_ids') or {}))}"
    f = next(f for f in s["findings"] if f["claim_id"] == cid)
    assert f["stance"] == g["stance"], f"{f['outcome']}: expected {g['stance']}, got {f['stance']} ({f['orientation']})"


def test_sat_fat_has_no_false_contradictions(reports):
    """The three contradicting studies behind the old 'Mixed / conflicting' verdict were all pipeline errors."""
    r = reports("sat-fat")
    assert r["verdict"]["label"] != "Mixed / conflicting"
    contra = [s["paper_id"] for s in r["studies"] if s["counted"] and s["headline"]["stance"] == "unfavorable"]
    assert not set(contra) & {369, 373, 74}
    scoped = {x["paper_id"]: x["reason"] for x in r["scope_exclusions"]}
    assert scoped.get(358) == "population_out_of_scope" and scoped.get(376) == "population_out_of_scope"
    assert all(x["detail"] for x in r["scope_exclusions"]), "every scope exclusion must carry a logged reason"


def test_every_verdict_is_judged_on_one_outcome_tier(reports):
    for topic in QUESTIONS:
        r = reports(topic)
        tier = r["tiers"].get("primary")
        for s in r["studies"]:
            if s["counted"]:
                assert s["headline"]["tier"] == tier, (topic, s["paper_id"])
