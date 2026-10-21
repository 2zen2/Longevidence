"""Full-text extraction with passage-level citations, using a scripted model (no network)."""
import pytest

from app.claims.materialize import materialize_fulltext, materialize_paper
from app.db import connect, jsonb
from app.documents.abstract import parse_abstract
from app.documents.jats import parse_jats
from app.documents.store import store_document
from app.extraction.fulltext import FT_PROMPT_VERSION, run_paper, select_passages
from app.extraction.llm import LLMResponse
from app.synthesis.report import build_report
from tests.test_claims_audit_db import ABSTRACT, SECTIONS
from tests.test_documents import XML

pytestmark = pytest.mark.db


class Scripted:
    model, provider = "scripted", "test"

    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def complete(self, key, system, user, schema):
        self.calls += 1
        return LLMResponse(self.fn(user), {"input_tokens": 1, "output_tokens": 1}, self.model)


def uid_of(user: str, startswith: str) -> str:
    """uid of the passage whose text starts with `startswith`, read from the prompt the model was shown."""
    for block in user.split("\n\n"):
        if block.startswith("[") and startswith in block:
            return block[1:block.index("]")]
    raise AssertionError(startswith)


@pytest.fixture
def paper(test_db):
    with connect() as c:
        pid = c.execute("INSERT INTO papers (title, abstract, journal) VALUES ('Drug X in heart failure', %s, 'J') RETURNING id", (ABSTRACT,)).fetchone()["id"]
        store_document(c, pid, parse_abstract(ABSTRACT, SECTIONS))
        store_document(c, pid, parse_jats(XML), raw_sha256="x")
        c.commit()
        yield pid, c


GOOD = "The primary outcome occurred less often with drug X (hazard ratio 0.74, 95% CI 0.63-0.88; P<0.001)."


def finding(uid, quote=GOOD, **kw):
    return {"passage_uid": uid, "outcome": "Primary outcome", "scope": "overall", "direction": "favors_intervention", "effect_measure": "HR",
            "effect_value": 0.74, "ci_low": 0.63, "ci_high": 0.88, "p_value": 0.001, "quote": quote, **kw}


def test_selection_keeps_results_with_statistics(paper):
    pid, c = paper
    ps = c.execute("SELECT p.uid, p.ordinal, p.section, p.kind, p.label, p.text FROM passages p JOIN documents d ON d.id=p.document_id WHERE d.kind='pmc_jats' ORDER BY ordinal").fetchall()
    sel = select_passages(ps)
    assert any("hazard ratio" in p["text"] for p in sel) and not any(p["section"] == "methods" for p in sel)


def test_verified_quote_links_to_the_cited_passage(paper):
    pid, c = paper
    cl = Scripted(lambda u: {"findings": [finding(uid_of(u, "The primary outcome"))], "limitations": []})
    assert run_paper(c, pid, cl) == "ok" and run_paper(c, pid, cl) == "cached" and cl.calls == 1
    st = materialize_fulltext(c, pid)
    assert st["ft_claims"] == 1 and st["ft_verified"] == 1
    row = c.execute("SELECT p.uid, substr(p.text, ce.quote_start+1, ce.quote_end-ce.quote_start) seg, ce.origin FROM claim_evidence ce "
                    "JOIN passages p ON p.id=ce.passage_id JOIN claims cl ON cl.id=ce.claim_id WHERE cl.ft_run_id IS NOT NULL").fetchone()
    assert row["seg"] == GOOD and row["origin"] == "extractor_quote"


def test_wrong_uid_is_corrected_and_fabricated_quote_is_unsupported(paper):
    pid, c = paper
    def fn(u):
        other = uid_of(u, "We randomized")   # not the passage the quote is in
        return {"findings": [finding(other),
                             finding(other, quote="Drug X cut mortality by 74% (HR 0.74, 95% CI 0.63-0.88).", outcome="Mortality")], "limitations": []}
    assert run_paper(c, pid, Scripted(fn)) == "ok"
    materialize_fulltext(c, pid)
    got = {r["claim_key"]: r for r in c.execute("SELECT claim_key, extraction_status, status_reasons FROM claims WHERE ft_run_id IS NOT NULL")}
    assert got["ft.finding.0"]["extraction_status"] == "verified"            # relinked to the right passage, soft note only
    assert got["ft.finding.1"]["extraction_status"] == "unsupported"         # fabricated: kept, never counted
    assert c.execute("SELECT count(*) n FROM claim_evidence ce JOIN claims cl ON cl.id=ce.claim_id WHERE cl.claim_key='ft.finding.1'").fetchone()["n"] == 0


def test_number_not_in_quote_fails(paper):
    pid, c = paper
    run_paper(c, pid, Scripted(lambda u: {"findings": [finding(uid_of(u, "The primary outcome"), effect_value=0.64)], "limitations": []}))
    materialize_fulltext(c, pid)
    assert c.execute("SELECT extraction_status s FROM claims WHERE ft_run_id IS NOT NULL").fetchone()["s"] == "needs_review"


def test_invalid_output_gets_one_repair_then_error_status(paper):
    pid, c = paper
    cl = Scripted(lambda u: {"findings": [{"nonsense": 1}]})
    assert run_paper(c, pid, cl) == "invalid" and cl.calls == 2


def test_duplicate_of_abstract_finding_is_skipped_and_subgroup_scope_excluded_from_verdict(paper):
    pid, c = paper
    out = {"extraction": {"study": {"design": {"status": "reported", "value": "rct", "quote": "Randomized, double-blind, placebo-controlled trial of 200 adults with drug X.",
                                               "verification": "exact", "char_start": 37 + 9, "char_end": 37 + 9 + 70, "notes": []}},
                          "primary_findings": [{"outcome": "Primary outcome", "direction": "favors_intervention", "effect_measure": "HR", "effect_value": 0.74, "ci_low": 0.63,
                                                "ci_high": 0.88, "p_value": 0.001, "quote": "hazard ratio 0.74, 95% CI 0.63-0.88; P<0.001", "verification": "exact",
                                                "char_start": ABSTRACT.index("hazard ratio"), "char_end": ABSTRACT.index("hazard ratio") + 44, "notes": []}],
                          "limitations_stated": [], "flags": []}}
    c.execute("INSERT INTO extraction_runs (paper_id, model_name, prompt_version, schema_version, input_hash, output, status) VALUES (%s,'m','v2','1','h',%s,'ok')", (pid, jsonb(out)))
    materialize_paper(c, pid)
    cl = Scripted(lambda u: {"findings": [finding(uid_of(u, "The primary outcome")),
                                         finding(uid_of(u, "The primary outcome"), outcome="Primary outcome in quartile 1", scope="subgroup",
                                                 effect_value=0.74, ci_low=0.63, ci_high=0.88)], "limitations": []})
    run_paper(c, pid, cl)
    st = materialize_fulltext(c, pid)
    assert st["ft_duplicates"] == 2 and st["ft_claims"] == 0              # same estimate+interval as the abstract finding
    # a genuinely new subgroup result is kept but flagged out of the headline
    second = Scripted(lambda u: {"findings": [finding(uid_of(u, "The primary outcome"), outcome="Primary outcome in quartile 1", scope="subgroup",
                                                       effect_value=0.9, ci_low=0.63, ci_high=0.88, quote=GOOD.replace("0.74", "0.9"))], "limitations": []})
    second.model = "scripted-2"
    run_paper(c, pid, second)
    assert materialize_fulltext(c, pid)["ft_claims"] == 1
