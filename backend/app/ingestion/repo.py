"""Persistence + cross-source identifier resolution. One paper = one transaction."""
from dataclasses import asdict

from ..db import jsonb
from .normalize import sha256
from .openalex import OpenAlexWork, reconcile
from .pubmed import PubMedRecord


class IdentifierConflict(Exception):
    """Identifiers of one incoming record point at >1 existing papers. Never auto-merged."""


def identifiers_for(rec: PubMedRecord, work: OpenAlexWork | None) -> list[tuple[str, str, str]]:
    ids = [("pubmed", "pmid", rec.pmid)]
    if rec.doi:
        ids.append(("pubmed", "doi", rec.doi))
    if rec.pmcid:
        ids.append(("pubmed", "pmc", rec.pmcid))
    if work:
        ids.append(("openalex", "openalex_id", work.openalex_id))
        if work.doi:
            ids.append(("openalex", "doi", work.doi))
    return ids


def resolve_paper_id(conn, ids: list[tuple[str, str, str]]) -> int | None:
    """Match on (identifier_type, value) *regardless of source*: this is what lets an OpenAlex
    DOI match a PubMed DOI. Returns None if new; raises IdentifierConflict on ambiguity."""
    found: set[int] = set()
    for _src, typ, val in ids:
        for row in conn.execute("SELECT DISTINCT paper_id FROM paper_identifiers "
                                "WHERE identifier_type=%s AND identifier_value=%s", (typ, val)):
            found.add(row["paper_id"])
    if len(found) > 1:
        raise IdentifierConflict(f"identifiers {ids} match papers {sorted(found)}")
    return found.pop() if found else None


def content_hash(rec: PubMedRecord) -> str:
    return sha256(rec.title, rec.abstract_text or "", rec.journal or "",
                  rec.publication_date.isoformat() if rec.publication_date else "",
                  "|".join(sorted(rec.publication_types)))


def upsert_paper(conn, rec: PubMedRecord, work: OpenAlexWork | None) -> tuple[int, str]:
    """Insert or update one paper. Returns (paper_id, 'inserted'|'updated'|'unchanged')."""
    ids = identifiers_for(rec, work)
    paper_id = resolve_paper_id(conn, ids)
    chash = content_hash(rec)
    meta = {"pubmed": {"pmid": rec.pmid, "publication_types": rec.publication_types, "mesh": rec.mesh,
                       "flags": rec.flags, "date_precision": rec.date_precision}}
    if work:
        meta["openalex"] = asdict(work)
        meta["reconciliation"] = reconcile(
            rec.title, rec.publication_date.year if rec.publication_date else None, rec.doi, work)
    study_type = "; ".join(rec.publication_types) or None

    if paper_id is None:
        paper_id = conn.execute(
            "INSERT INTO papers (title, abstract, publication_date, journal, study_type, source_metadata, content_hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (rec.title, rec.abstract_text, rec.publication_date, rec.journal, study_type, jsonb(meta), chash),
        ).fetchone()["id"]
        outcome = "inserted"
    else:
        old = conn.execute("SELECT content_hash, source_metadata FROM papers WHERE id=%s FOR UPDATE",
                           (paper_id,)).fetchone()
        merged = {**(old["source_metadata"] or {}), **meta}
        if old["content_hash"] == chash and merged == old["source_metadata"]:
            outcome = "unchanged"
        else:
            conn.execute(
                "UPDATE papers SET title=%s, abstract=%s, publication_date=%s, journal=%s, study_type=%s, "
                "source_metadata=%s, content_hash=%s, updated_at=now() WHERE id=%s",
                (rec.title, rec.abstract_text, rec.publication_date, rec.journal, study_type,
                 jsonb(merged), chash, paper_id))
            outcome = "updated"

    for src, typ, val in ids:
        conn.execute("INSERT INTO paper_identifiers (paper_id, source, identifier_type, identifier_value) "
                     "VALUES (%s,%s,%s,%s) ON CONFLICT (source, identifier_type, identifier_value) DO NOTHING",
                     (paper_id, src, typ, val))
    if rec.abstract_text:
        th = sha256(rec.abstract_text)
        conn.execute(
            "INSERT INTO source_texts (paper_id, source_kind, text, sections, text_hash) "
            "VALUES (%s,'pubmed_abstract',%s,%s,%s) "
            "ON CONFLICT (paper_id, source_kind) DO UPDATE SET text=EXCLUDED.text, sections=EXCLUDED.sections, "
            "text_hash=EXCLUDED.text_hash WHERE source_texts.text_hash <> EXCLUDED.text_hash",
            (paper_id, rec.abstract_text, jsonb(rec.sections), th))
    return paper_id, outcome
