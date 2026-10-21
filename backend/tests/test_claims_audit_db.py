"""End to end on a throwaway Postgres: abstract -> passages -> claims linked to passages -> audit that catches tampering."""
import pytest

from app.db import connect, jsonb
from app.documents.abstract import parse_abstract
from app.documents.jats import parse_jats
from app.documents.store import store_document
from app.claims.materialize import materialize_paper
from app.synthesis.audit import audit_statements
from app.synthesis.report import build_report
from tests.test_documents import XML

pytestmark = pytest.mark.db

ABSTRACT = ("BACKGROUND: Heart failure is common.\n"
            "METHODS: Randomized, double-blind, placebo-controlled trial of 200 adults with drug X.\n"
            "RESULTS: The primary outcome occurred less often with drug X (hazard ratio 0.74, 95% CI 0.63-0.88; P<0.001).")
SECTIONS = [{"label": "BACKGROUND", "start": 0, "end": 36}, {"label": "METHODS", "start": 37, "end": 119}, {"label": "RESULTS", "start": 120, "end": len(ABSTRACT)}]


def q(text):
    i = ABSTRACT.index(text)
    return {"quote": text, "char_start": i, "char_end": i + len(text), "verification": "exact", "notes": [], "section": None, "confidence": "high"}


@pytest.fixture
def seeded(test_db):
    with connect() as c:
        pid = c.execute("INSERT INTO papers (title, abstract, journal, publication_date, source_metadata) VALUES "
                        "('Drug X in heart failure', %s, 'J Test', '2025-01-01', %s) RETURNING id", (ABSTRACT, jsonb({"pubmed": {"publication_types": ["Randomized Controlled Trial"]}}))).fetchone()["id"]
        c.execute("INSERT INTO source_texts (paper_id, source_kind, text, sections, text_hash) VALUES (%s,'pubmed_abstract',%s,%s,'h')", (pid, ABSTRACT, jsonb(SECTIONS)))
        store_document(c, pid, parse_abstract(ABSTRACT, SECTIONS))
        store_document(c, pid, parse_jats(XML), raw_sha256="x")
        finding = {"outcome": "Primary outcome", "direction": "favors_intervention", "effect_measure": "HR", "effect_value": 0.74,
                   "ci_low": 0.63, "ci_high": 0.88, "p_value": 0.001, **q("hazard ratio 0.74, 95% CI 0.63-0.88; P<0.001")}
        out = {"extraction": {"study": {
            "design": {"status": "reported", "value": "rct", **q("Randomized, double-blind, placebo-controlled trial")},
            "sample_size": {"status": "reported", "value": 200, **q("200 adults")},
            "population": {"status": "not_reported"}, "intervention": {"status": "reported", "value": "drug X", **q("drug X")},
            "comparator": {"status": "not_reported"}, "follow_up": {"status": "not_reported"}},
            "primary_findings": [finding], "limitations_stated": [], "flags": []}}
        c.execute("INSERT INTO extraction_runs (paper_id, model_name, prompt_version, schema_version, input_hash, output, status) "
                  "VALUES (%s,'m','v2','1','h',%s,'ok')", (pid, jsonb(out)))
        c.commit()
        yield pid, c


def test_claims_link_to_passages_and_numbers_are_corroborated_in_fulltext(seeded):
    pid, c = seeded
    stats = materialize_paper(c, pid)
    assert stats["claims"] == 4 and stats["verified"] == 4
    f = c.execute("SELECT id FROM claims WHERE claim_key='finding.0'").fetchone()["id"]
    links = c.execute("SELECT ce.origin, p.kind, substr(p.text, ce.quote_start+1, ce.quote_end-ce.quote_start) seg FROM claim_evidence ce "
                      "JOIN passages p ON p.id=ce.passage_id WHERE ce.claim_id=%s ORDER BY ce.origin", (f,)).fetchall()
    assert [l["origin"] for l in links] == ["extractor_quote", "numeric_match"]
    assert links[0]["seg"] == "hazard ratio 0.74, 95% CI 0.63-0.88; P<0.001"        # offsets round-trip exactly
    assert "0.74" in links[1]["seg"] and links[1]["kind"] == "paragraph"               # independent full-text corroboration


def test_rematerializing_is_idempotent(seeded):
    pid, c = seeded
    materialize_paper(c, pid)
    materialize_paper(c, pid)
    assert c.execute("SELECT count(*) n FROM claims").fetchone()["n"] == 4


def test_audit_passes_then_fails_when_the_stored_passage_is_tampered(seeded):
    pid, c = seeded
    materialize_paper(c, pid)
    cid = c.execute("SELECT id FROM claims WHERE claim_key='finding.0'").fetchone()["id"]
    st = [{"id": "s1", "kind": "study", "requires_citation": True, "claim_ids": [cid], "text": "x"}]
    assert audit_statements(c, st)["failed"] == 0
    c.execute("UPDATE passages SET text=replace(text,'0.74','0.99') WHERE kind='abstract_section' AND text LIKE '%%0.74%%'")
    c.execute("UPDATE passages SET text=replace(text,'0.74','0.99') WHERE text LIKE '%%0.74%%'")
    res = audit_statements(c, st)
    assert res["failed"] == 1 and any("effect_value" in p for p in res["results"][0]["problems"])


def test_audit_rejects_uncited_and_unverified_claims(seeded):
    pid, c = seeded
    materialize_paper(c, pid)
    cid = c.execute("SELECT id FROM claims WHERE claim_key='finding.0'").fetchone()["id"]
    assert audit_statements(c, [{"id": "a", "kind": "headline", "requires_citation": True, "claim_ids": [], "text": ""}])["failed"] == 1
    c.execute("UPDATE claims SET extraction_status='needs_review' WHERE id=%s", (cid,))
    assert audit_statements(c, [{"id": "b", "kind": "study", "requires_citation": True, "claim_ids": [cid], "text": ""}])["failed"] == 1
    assert audit_statements(c, [{"id": "c", "kind": "caveat", "requires_citation": False, "claim_ids": [], "text": ""}])["failed"] == 0


def test_report_only_cites_verified_claims_and_is_cached(seeded):
    pid, c = seeded
    materialize_paper(c, pid)
    r = build_report(c, "Does drug X reduce the primary outcome in heart failure?")   # free text -> keyword relevance
    assert r["counts"]["retrieved"] == 1 and r["audit"]["failed"] == 0
    cited = {cid for s in r["conclusion"] for cid in s["claim_ids"]}
    ok = {x["id"] for x in c.execute("SELECT id FROM claims WHERE extraction_status='verified'")}
    assert cited and cited <= ok
    assert build_report(c, "Does drug X reduce the primary outcome in heart failure?")["cached"] is True
