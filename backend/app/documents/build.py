"""Build documents + passages for the corpus.

    python -m app.documents.build                 # abstracts for every paper (offline)
    python -m app.documents.build --fulltext      # also fetch open-access full text from Europe PMC for papers with a PMCID
    python -m app.documents.build --fulltext --paper 12
"""
import argparse
import logging

from ..db import connect
from .abstract import parse_abstract
from .europepmc import BASE, EuropePMC, save_raw
from .jats import parse_jats
from .store import store_document

log = logging.getLogger("documents")


def build_abstracts(conn, paper_ids: list[int] | None = None) -> dict:
    n = changed = 0
    for r in conn.execute("SELECT paper_id, text, sections FROM source_texts WHERE source_kind='pubmed_abstract' "
                          "AND (%s::bigint[] IS NULL OR paper_id = ANY(%s)) ORDER BY paper_id", (paper_ids, paper_ids)).fetchall():
        _, ch = store_document(conn, r["paper_id"], parse_abstract(r["text"], r["sections"]))
        n += 1
        changed += ch
    conn.commit()
    return {"abstract_documents": n, "changed": changed}


def reparse_fulltext(conn) -> dict:
    """Re-run the current parser over the raw files kept on disk (no network). Replaces documents whose parser version changed."""
    from ..config import settings
    n = changed = 0
    for d in conn.execute("SELECT paper_id, raw_path, raw_sha256, source_url FROM documents WHERE kind='pmc_jats' AND raw_path IS NOT NULL").fetchall():
        doc = parse_jats((settings.data_dir / d["raw_path"]).read_bytes())
        _, ch = store_document(conn, d["paper_id"], doc, source_url=d["source_url"], raw_path=d["raw_path"], raw_sha256=d["raw_sha256"])
        n += 1
        changed += ch
    conn.commit()
    return {"reparsed": n, "changed": changed}


def _attempt(conn, paper_id: int, status: str, detail: str | None = None) -> None:
    conn.execute("INSERT INTO fulltext_attempts (paper_id, source, status, detail) VALUES (%s,'europepmc',%s,%s) "
                 "ON CONFLICT (paper_id, source) DO UPDATE SET status=EXCLUDED.status, detail=EXCLUDED.detail, attempted_at=now()",
                 (paper_id, status, detail))


def build_fulltext(conn, paper_ids: list[int] | None = None, retry: bool = False, epmc: EuropePMC | None = None) -> dict:
    epmc = epmc or EuropePMC()
    counts: dict[str, int] = {}
    q = ("SELECT p.id, (SELECT identifier_value FROM paper_identifiers WHERE paper_id=p.id AND identifier_type='pmc' LIMIT 1) AS pmc, "
         "(SELECT status FROM fulltext_attempts a WHERE a.paper_id=p.id AND a.source='europepmc') AS prev FROM papers p ORDER BY p.id")
    for r in conn.execute(q).fetchall():
        if paper_ids and r["id"] not in paper_ids:
            continue
        if not r["pmc"]:
            _attempt(conn, r["id"], "no_pmcid")
            conn.commit()
            counts["no_pmcid"] = counts.get("no_pmcid", 0) + 1
            continue
        if r["prev"] == "ok" and not retry:
            counts["cached"] = counts.get("cached", 0) + 1
            continue
        try:
            xml = epmc.fulltext_xml(r["pmc"])
            if xml is None:
                _attempt(conn, r["id"], "not_available")
                counts["not_available"] = counts.get("not_available", 0) + 1
                conn.commit()
                continue
            doc = parse_jats(xml)
            if len(doc.passages) < 5:
                _attempt(conn, r["id"], "error", f"parsed only {len(doc.passages)} passages")
                counts["error"] = counts.get("error", 0) + 1
                conn.commit()
                continue
            raw_path, digest = save_raw(r["id"], xml)
            store_document(conn, r["id"], doc, source_url=f"{BASE}/{r['pmc']}/fullTextXML", raw_path=raw_path, raw_sha256=digest)
            _attempt(conn, r["id"], "ok", f"{len(doc.passages)} passages; license={doc.license or 'not stated'}")
            counts["ok"] = counts.get("ok", 0) + 1
            log.info("paper %s %s: %d passages, license=%s", r["id"], r["pmc"], len(doc.passages), doc.license)
        except Exception as e:                       # one bad paper must not stop the batch
            log.warning("paper %s %s failed: %r", r["id"], r["pmc"], e)
            conn.rollback()
            _attempt(conn, r["id"], "error", repr(e)[:300])
            counts["error"] = counts.get("error", 0) + 1
        conn.commit()
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--fulltext", action="store_true")
    ap.add_argument("--paper", type=int, action="append")
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--reparse", action="store_true", help="re-run the parser over the saved raw files (offline)")
    a = ap.parse_args()
    with connect() as c:
        print(build_abstracts(c))
        if a.reparse:
            print(reparse_fulltext(c))
        if a.fulltext:
            print(build_fulltext(c, a.paper, a.retry))
