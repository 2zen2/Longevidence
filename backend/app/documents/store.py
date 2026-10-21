"""Persist parsed documents + passages. Idempotent per (paper, kind): unchanged text is a no-op; changed text replaces the
document and its passages (claim links to the old passages cascade away and are rebuilt by claims.materialize)."""
from ..db import jsonb
from .model import ParsedDocument, passage_uid


def store_document(conn, paper_id: int, doc: ParsedDocument, *, source_url: str | None = None,
                   raw_path: str | None = None, raw_sha256: str | None = None) -> tuple[int, bool]:
    """Returns (document_id, changed)."""
    cur = conn.execute("SELECT id, text_hash, parser_version FROM documents WHERE paper_id=%s AND kind=%s", (paper_id, doc.kind)).fetchone()
    if cur and cur["text_hash"] == doc.text_hash and cur["parser_version"] == doc.parser_version:
        return cur["id"], False
    if cur:
        conn.execute("DELETE FROM documents WHERE id=%s", (cur["id"],))
    row = conn.execute(
        "INSERT INTO documents (paper_id, kind, source_url, license, raw_path, raw_sha256, text, text_hash, parser_version, printed_pages, meta) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (paper_id, doc.kind, source_url, doc.license, raw_path, raw_sha256, doc.text, doc.text_hash, doc.parser_version,
         doc.printed_pages, jsonb(doc.meta))).fetchone()
    for i, p in enumerate(doc.passages):
        assert doc.text[p.start:p.end] == p.text, f"offset mismatch in passage {i}"
        conn.execute(
            "INSERT INTO passages (uid, document_id, paper_id, ordinal, section, section_title, kind, label, page_number, printed_page, "
            "text, start_offset, end_offset, table_json, text_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (passage_uid(doc.text_hash, p.start, p.end), row["id"], paper_id, i, p.section, p.section_title, p.kind, p.label,
             p.page_number, p.printed_page, p.text, p.start, p.end, jsonb(p.table_json) if p.table_json else None,
             __import__("hashlib").sha256(p.text.encode()).hexdigest()))
    return row["id"], True
