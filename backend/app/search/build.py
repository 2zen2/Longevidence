"""Compute and store embeddings (incremental: only new or changed text is embedded).

    python -m app.search.build            # papers (title + abstract) and full-text passages
"""
import logging

from ..db import connect
from .embed import MODEL, embed_docs
from .index import text_hash

log = logging.getLogger("search.build")
BATCH = 64


def _todo(conn, kind: str, rows: list[tuple[int, str]]) -> list[tuple[int, str, str]]:
    have = {r["ref_id"]: r["text_hash"] for r in conn.execute("SELECT ref_id, text_hash FROM embeddings WHERE kind=%s AND model=%s", (kind, MODEL))}
    return [(i, t, text_hash(t)) for i, t in rows if t and have.get(i) != text_hash(t)]


def build(paper_ids: list[int] | None = None) -> dict:
    """Embed what is missing or changed. paper_ids limits the work to those papers (and their full-text passages)."""
    out = {}
    with connect() as conn:
        papers = [(r["id"], f"{r['title']}. {r['abstract'] or ''}") for r in conn.execute(
            "SELECT id, title, abstract FROM papers WHERE (%s::bigint[] IS NULL OR id = ANY(%s))", (paper_ids, paper_ids))]
        passages = [(r["id"], r["text"][:2000]) for r in conn.execute(
            "SELECT p.id, p.text FROM passages p JOIN documents d ON d.id=p.document_id WHERE d.kind='pmc_jats' AND p.kind IN ('paragraph','table','figure_caption') "
            "AND (%s::bigint[] IS NULL OR p.paper_id = ANY(%s))", (paper_ids, paper_ids))]
        for kind, rows in (("paper", papers), ("passage", passages)):
            todo = _todo(conn, kind, rows)
            for i in range(0, len(todo), BATCH):
                chunk = todo[i:i + BATCH]
                vecs = embed_docs([t for _, t, _ in chunk])
                for (ref, _, h), v in zip(chunk, vecs):
                    conn.execute("INSERT INTO embeddings (kind, ref_id, model, text_hash, vec) VALUES (%s,%s,%s,%s,%s) "
                                 "ON CONFLICT (kind, ref_id, model) DO UPDATE SET text_hash=EXCLUDED.text_hash, vec=EXCLUDED.vec",
                                 (kind, ref, MODEL, h, v.astype("float32").tobytes()))
                conn.commit()
                log.info("%s: %d/%d", kind, min(i + BATCH, len(todo)), len(todo))
            out[kind] = {"embedded": len(todo), "total": len(rows)}
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(build())
