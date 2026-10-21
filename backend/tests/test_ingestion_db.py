"""Idempotent ingestion + cross-source identifier resolution against a real (throwaway) Postgres."""
import pytest

from app.ingestion.openalex import OpenAlexWork
from app.ingestion.pubmed import parse_efetch
from app.ingestion.repo import IdentifierConflict, upsert_paper
from app.ingestion.sync import run_sync

pytestmark = pytest.mark.db


class FakePubMed:
    def __init__(self, xml, pmids):
        self.xml, self.pmids = xml, pmids

    def search(self, q, retmax=30, sort="pub_date"):
        return self.pmids, len(self.pmids)

    def fetch(self, pmids):
        return [r for r in parse_efetch(self.xml) if r.pmid in pmids]


class FakeOpenAlex:
    def __init__(self, fail_for=()):
        self.fail_for = set(fail_for)

    def get_by(self, pmid, doi):
        if pmid in self.fail_for:
            raise RuntimeError("openalex down")
        if pmid != "111":
            return None
        return OpenAlexWork("W1", "10.1000/abc.1", pmid, "Drug X in heart failure: a randomized trial.", 2024,
                            12, True, "gold", "https://x", "article", False)


def counts(conn, table):
    return conn.execute(f"SELECT count(*) n FROM {table}").fetchone()["n"]


def test_double_import_is_idempotent(test_db, efetch_xml):
    from app.db import connect
    kw = dict(pubmed=FakePubMed(efetch_xml, ["111", "222", "333"]), openalex=FakeOpenAlex())
    r1 = run_sync("q", "query", **kw)
    with connect() as c:
        first = c.execute("SELECT counts, status FROM sync_runs WHERE id=%s", (r1,)).fetchone()
        n_ids, n_papers = counts(c, "paper_identifiers"), counts(c, "papers")
        stamp = c.execute("SELECT max(updated_at) t FROM papers").fetchone()["t"]
    assert first["counts"]["inserted"] == 3 and first["counts"]["no_abstract"] == 1
    r2 = run_sync("q", "query", **kw)
    with connect() as c:
        second = c.execute("SELECT counts FROM sync_runs WHERE id=%s", (r2,)).fetchone()["counts"]
        assert (counts(c, "paper_identifiers"), counts(c, "papers")) == (n_ids, n_papers)
        assert c.execute("SELECT max(updated_at) t FROM papers").fetchone()["t"] == stamp   # untouched rows
    assert second["inserted"] == 0 and second["unchanged"] == 3 and second["updated"] == 0


def test_cross_source_identifier_resolution(test_db, efetch_xml):
    from app.db import connect
    run_sync("q", "query", pubmed=FakePubMed(efetch_xml, ["111"]), openalex=FakeOpenAlex())
    with connect() as c:
        rows = c.execute("SELECT source, identifier_type, identifier_value FROM paper_identifiers").fetchall()
        types = {(r["source"], r["identifier_type"]) for r in rows}
        assert {("pubmed", "pmid"), ("pubmed", "doi"), ("openalex", "openalex_id"), ("openalex", "doi")} <= types
        assert len({r["paper_id"] for r in c.execute("SELECT paper_id FROM paper_identifiers")}) == 1


def test_changed_content_updates_once(test_db, efetch_xml):
    from app.db import connect
    rec = parse_efetch(efetch_xml)[0]
    with connect() as c:
        pid, o1 = upsert_paper(c, rec, None)
        c.commit()
        rec.title = "Corrected title"
        _, o2 = upsert_paper(c, rec, None)
        _, o3 = upsert_paper(c, rec, None)
        c.commit()
        assert (o1, o2, o3) == ("inserted", "updated", "unchanged")
        assert c.execute("SELECT title FROM papers WHERE id=%s", (pid,)).fetchone()["title"] == "Corrected title"


def test_identifier_conflict_is_reported_not_merged(test_db, efetch_xml):
    from app.db import connect
    a, b = parse_efetch(efetch_xml)[0], parse_efetch(efetch_xml)[2]
    with connect() as c:
        upsert_paper(c, a, None)
        b.pmid = "333"
        upsert_paper(c, b, None)
        c.commit()
        clash = parse_efetch(efetch_xml)[0]
        clash.pmid = "333"            # PMID of paper B, DOI of paper A
        with pytest.raises(IdentifierConflict):
            upsert_paper(c, clash, None)


def test_partial_failure_is_logged_and_batch_continues(test_db, efetch_xml):
    from app.db import connect
    rid = run_sync("q", "query", pubmed=FakePubMed(efetch_xml, ["111", "222", "999"]),
                   openalex=FakeOpenAlex(fail_for={"111"}))
    with connect() as c:
        row = c.execute("SELECT status, counts, errors FROM sync_runs WHERE id=%s", (rid,)).fetchone()
        assert counts(c, "papers") == 2
    assert row["status"] == "partial" and row["counts"]["failed"] == 1 and row["counts"]["inserted"] == 2
    assert {e["stage"] for e in row["errors"]} == {"parse", "openalex"}
