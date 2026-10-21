"""Longevity questions from the take-home, answered from the stored corpus. The model is never called: a client that always fails is injected, so
only readings already in llm_cache (shipped with the seed) are replayed (skipped on an empty dev database).
Pins: each question counts at least some studies, the verdict carries a caveats block, and every safety sentence is a verbatim substring of its
stored passage."""
import pytest

from app.db import connect
from app.synthesis import llm_assist
from app.synthesis.report import build_report

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def conn():
    try:
        c = connect()
        n = c.execute("SELECT count(*) n FROM papers p JOIN question_papers qp ON qp.paper_id=p.id JOIN research_questions q ON q.id=qp.question_id "
                      "WHERE q.query ILIKE '%nicotinamide mononucleotide%'").fetchone()["n"]
    except Exception:
        pytest.skip("no dev database")
    if n < 5:
        pytest.skip("longevity corpus not loaded")
    class Offline:
        model = "offline"

        def complete(self, *a, **k):
            raise RuntimeError("no network in tests")
    llm_assist.set_client(Offline())
    yield c
    llm_assist.set_client(None)
    c.close()


@pytest.mark.parametrize("q,minimum", [
    ("Does NMN raise NAD+ levels?", 2),
    ("Does cold water immersion after resistance training reduce muscle growth?", 2),
    ("Does whole-body MRI screening detect cancer in healthy adults?", 1)])
def test_longevity_question_is_answered_with_caveats(conn, q, minimum):
    r = build_report(conn, q, refresh=True)
    assert r["counts"]["counted"] >= minimum
    cav = r["caveats"]
    assert cav["applies_to"]["studies"] == r["counts"]["counted"]
    assert cav["populations"] and isinstance(cav["notes"], list)
    for x in cav["safety"]:
        text = r["passages"][x["passage_uid"]]["text"]
        assert text[x["quote_start"]:x["quote_end"]] == x["quote"]


def test_no_counted_studies_gives_empty_caveats(conn):
    r = build_report(conn, "Does garlic lower blood pressure?", refresh=True)
    assert r["caveats"]["applies_to"] is None and r["caveats"]["safety"] == []
