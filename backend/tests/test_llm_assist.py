"""Model assist at answer time: cached, capped, off without a key, and unable to invent evidence (it only picks stored findings)."""
from types import SimpleNamespace

import pytest

from app.config import settings
from app.db import connect
from app.synthesis import llm_assist as L
from app.synthesis.interpret import from_model_reading, interpret


class Fake:
    model = "fake/model"

    def __init__(self, output):
        self.output, self.calls = output, 0

    def complete(self, key, system, user, schema):
        self.calls += 1
        return SimpleNamespace(output=self.output, usage={"input_tokens": 10, "output_tokens": 5}, model=self.model)


@pytest.fixture
def conn():
    try:
        c = connect()
        c.execute("SELECT 1 FROM llm_cache LIMIT 1")
    except Exception:
        pytest.skip("no dev database")
    yield c
    c.execute("DELETE FROM llm_cache WHERE model='fake/model'")
    c.commit()
    c.close()
    L.set_client(None)


def test_disabled_without_client_under_tests():
    assert not L.enabled()


def test_reading_builds_interpretation_with_specific_exposure():
    m = {"exposure": "vitamin D supplementation", "exposure_synonyms": ["cholecalciferol", "ergocalciferol"],
         "outcomes": ["fractures", "bone mineral density (BMD)"], "polarity": "benefit"}
    i = from_model_reading("Vitamin D makes bones stronger", m)
    assert i.model_read and i.polarity == "benefit" and i.polarity_source == "model"
    assert "vitd" in i.exposure_terms and "vitamin" not in i.exposure_terms
    assert i.outcome_terms == ["fractures", "bone mineral density"] and "cholecalciferol" in i.exposure_alias
    assert from_model_reading("q", m, polarity="harm").polarity == "harm"


def test_read_claim_is_cached(conn):
    f = Fake({"exposure": "coffee", "outcomes": ["liver enzymes"], "polarity": "benefit"})
    L.set_client(f)
    a = L.read_claim(conn, "Is zzz-test coffee good for your liver?")
    b = L.read_claim(conn, "is zzz-test coffee good for your liver")
    assert a == b and a["outcomes"] == ["liver enzymes"] and f.calls == 1


def test_bad_reading_is_rejected(conn):
    L.set_client(Fake({"exposure": "", "outcomes": [], "polarity": "benefit"}))
    assert L.read_claim(conn, "zzz-test nonsense") is None


def test_daily_cap_stops_calls(conn, monkeypatch):
    f = Fake({"exposure": "x", "outcomes": ["y"], "polarity": "harm"})
    L.set_client(f)
    monkeypatch.setattr(settings, "llm_daily_cap", 0)
    assert L.read_claim(conn, "zzz-test capped claim") is None and f.calls == 0


def test_judge_can_only_pick_stored_findings(conn):
    interp = interpret("Does green coffee extract improve liver enzymes?")
    out = {"findings": [{"claim_id": 1, "status": "verified", "subgroup": False, "outcome": "ALT", "quote": "ALT fell"},
                        {"claim_id": 2, "status": "unsupported", "subgroup": False, "outcome": "AST", "quote": "x"}],
           "design": "rct", "pico": {"intervention": "green coffee extract", "comparator": "placebo", "population": "adults"}}
    L.set_client(Fake({"studies_exposure": True, "relevant_finding_ids": [1, 2, 999], "reason": "ok"}))
    j = L.judge_paper(conn, interp, {"id": -1, "title": "zzz-test green coffee"}, out)
    assert j["relevant_ids"] == [1] and j["studies_exposure"]                      # 2 is unverified, 999 is invented


def test_concurrent_identical_calls_make_one_request(conn):
    import threading, time
    f = Fake({"exposure": "x", "outcomes": ["y"], "polarity": "benefit"})
    slow = f.complete
    f.complete = lambda *a: (time.sleep(0.4), slow(*a))[1]
    L.set_client(f)
    q = "zz concurrency probe claim"
    def run():
        c = connect()
        L.read_claim(c, q)
    ts = [threading.Thread(target=run) for _ in range(3)]
    [t.start() for t in ts]; [t.join() for t in ts]
    L.set_client(None)
    assert f.calls == 1
