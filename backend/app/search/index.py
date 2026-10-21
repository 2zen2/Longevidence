"""Hybrid search over the corpus: keyword (BM25), vector (embeddings) and metadata, fused with Reciprocal Rank Fusion.

  keyword  BM25 over title(x3)+abstract per paper, and over full-text passages (exact terms such as 'SGLT2', 'HR 0.74')
  vector   cosine similarity of bge-small embeddings: one per paper (title+abstract) and one per full-text passage
  metadata design, year, sample size, journal, full-text availability, verified-finding count: used as filters and facets
  fusion   RRF (k=60) over the four ranked lists; passage hits are folded into their paper (best passage wins and becomes the snippet)

Built lazily in memory from Postgres; only embeddings are stored (table `embeddings`, keyed by text hash, so `make index` is incremental)."""
import hashlib
import threading
from dataclasses import dataclass, field

import numpy as np

from ..db import connect
from .bm25 import BM25, tokenize

RRF_K = 60
DEFAULTS = {"weights": (1.5, 0.5, 1.0, 0.5), "rel_cut": 0.3, "dense_margin": 0.03}
_lock = threading.Lock()
_INDEX: "Index | None" = None


def text_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()[:16]


@dataclass
class Hit:
    paper_id: int
    score: float
    via: list[str] = field(default_factory=list)          # which indexes found it: keyword, semantic
    passage_uid: str | None = None
    passage_text: str | None = None
    passage_section: str | None = None
    passage_label: str | None = None


class Index:
    def __init__(self, conn, with_vectors: bool = True):
        from .embed import MODEL
        self.papers = {r["id"]: r for r in conn.execute(
            "SELECT p.id, p.title, p.abstract, p.journal, p.publication_date, p.source_metadata FROM papers p")}
        self.passages = {r["id"]: r for r in conn.execute(
            "SELECT p.id, p.paper_id, p.uid, p.section, p.label, p.kind, p.text FROM passages p JOIN documents d ON d.id=p.document_id "
            "WHERE d.kind='pmc_jats' AND p.kind IN ('paragraph','table','figure_caption')")}
        self.bm_papers = BM25({i: (p["abstract"] or "") for i, p in self.papers.items()}, field_boost={i: p["title"] or "" for i, p in self.papers.items()}, boost=3)
        self.bm_passages = BM25({i: p["text"] for i, p in self.passages.items()})
        self.meta = self._metadata(conn)
        self.vec_papers = self.vec_passages = None
        self.ids_papers: list[int] = []
        self.ids_passages: list[int] = []
        if with_vectors:
            for kind in ("paper", "passage"):
                rows = conn.execute("SELECT ref_id, vec FROM embeddings WHERE kind=%s AND model=%s ORDER BY ref_id", (kind, MODEL)).fetchall()
                if rows:
                    mat = np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
                    ids = [r["ref_id"] for r in rows]
                    if kind == "paper":
                        self.vec_papers, self.ids_papers = mat, ids
                    else:
                        self.vec_passages, self.ids_passages = mat, ids

    @property
    def has_vectors(self) -> bool:
        return self.vec_papers is not None

    # ------------------------------------------------------------------ metadata index
    def _metadata(self, conn) -> dict[int, dict]:
        meta: dict[int, dict] = {}
        for pid, p in self.papers.items():
            pm = (p["source_metadata"] or {}).get("pubmed", {})
            meta[pid] = {"year": p["publication_date"].year if p["publication_date"] else None, "journal": p["journal"],
                         "pubtypes": pm.get("publication_types", []), "design": None, "sample_size": None, "fulltext": False, "verified_findings": 0}
        for r in conn.execute("SELECT DISTINCT paper_id FROM documents WHERE kind='pmc_jats'"):
            meta[r["paper_id"]]["fulltext"] = True
        for r in conn.execute(
                "SELECT c.paper_id, c.claim_type, c.structured, c.extraction_status FROM claims c WHERE c.extraction_status IN ('verified','needs_review')"):
            m = meta.get(r["paper_id"])
            if not m:
                continue
            if r["claim_type"] == "design" and r["extraction_status"] == "verified":
                m["design"] = r["structured"].get("value")
            elif r["claim_type"] == "sample_size" and r["extraction_status"] == "verified" and isinstance(r["structured"].get("value"), (int, float)):
                m["sample_size"] = r["structured"]["value"]
            elif r["claim_type"] == "finding" and r["extraction_status"] == "verified":
                m["verified_findings"] += 1
        for pid, m in meta.items():                       # fall back to PubMed's publication type when no verified design claim
            if not m["design"]:
                for key, val in (("Meta-Analysis", "meta_analysis"), ("Systematic Review", "meta_analysis"), ("Randomized Controlled Trial", "rct"), ("Observational Study", "cohort")):
                    if key in m["pubtypes"]:
                        m["design"] = val
                        break
        return meta

    def allowed(self, design=None, year_min=None, min_n=None, fulltext=False, topic_ids: set[int] | None = None) -> set[int]:
        out = set()
        for pid, m in self.meta.items():
            if design and (m["design"] or "unknown") != design:
                continue
            if year_min and (not m["year"] or m["year"] < year_min):
                continue
            if min_n and (not m["sample_size"] or m["sample_size"] < min_n):
                continue
            if fulltext and not m["fulltext"]:
                continue
            if topic_ids is not None and pid not in topic_ids:
                continue
            out.add(pid)
        return out

    # ------------------------------------------------------------------ retrieval
    def _dense(self, q: str):
        from .embed import embed_query
        qv = embed_query(q)
        res = {}
        if self.vec_papers is not None:
            s = self.vec_papers @ qv
            res["paper"] = [(self.ids_papers[i], float(s[i])) for i in np.argsort(-s)[:40]]
        if self.vec_passages is not None:
            s = self.vec_passages @ qv
            res["passage"] = [(self.ids_passages[i], float(s[i])) for i in np.argsort(-s)[:80]]
        return res

    def search(self, q: str, mode: str = "hybrid", allowed: set[int] | None = None, limit: int = 50, min_cosine: float = 0.62,
               weights: tuple[float, float, float, float] | None = None, rel_cut: float | None = None, dense_margin: float | None = None) -> list[Hit]:
        w = weights or DEFAULTS["weights"]                           # (keyword paper, keyword passage, vector paper, vector passage)
        rel_cut = DEFAULTS["rel_cut"] if rel_cut is None else rel_cut
        dense_margin = DEFAULTS["dense_margin"] if dense_margin is None else dense_margin
        lists: list[tuple[str, str, list[tuple[int, float]]]] = []     # (source, unit, ranked)
        if mode in ("hybrid", "keyword"):
            lists.append(("keyword", "paper", self.bm_papers.search(q)))
            lists.append(("keyword", "passage", self.bm_passages.search(q)))
        if mode in ("hybrid", "semantic") and self.has_vectors:
            d = self._dense(q)
            def keep(rows):                                       # absolute floor, and (optionally) within a margin of the best cosine
                top = rows[0][1] if rows else 0
                return [x for x in rows if x[1] >= min_cosine and (dense_margin is None or x[1] >= top - dense_margin)]
            lists.append(("semantic", "paper", keep(d.get("paper", []))))
            lists.append(("semantic", "passage", keep(d.get("passage", []))))
        scores: dict[int, float] = {}
        via: dict[int, set[str]] = {}
        best_passage: dict[int, tuple[float, int]] = {}
        for li, (source, unit, ranked) in enumerate(lists):
            seen_papers: set[int] = set()
            wt = w[li] if mode == "hybrid" else 1.0
            rank = 0
            for ref, _ in ranked:
                pid = ref if unit == "paper" else self.passages[ref]["paper_id"]
                if pid in seen_papers:                       # a paper counts once per list, at its best rank
                    continue
                seen_papers.add(pid)
                rank += 1
                if allowed is not None and pid not in allowed:
                    continue
                scores[pid] = scores.get(pid, 0.0) + wt / (RRF_K + rank)
                via.setdefault(pid, set()).add(source)
                if unit == "passage":
                    prev = best_passage.get(pid)
                    if prev is None or rank < prev[0]:
                        best_passage[pid] = (rank, ref)
        hits = []
        ranked_scores = sorted(scores.items(), key=lambda x: -x[1])
        if mode == "hybrid" and ranked_scores and rel_cut:
            ranked_scores = [x for x in ranked_scores if x[1] >= rel_cut * ranked_scores[0][1]]
        for pid, sc in ranked_scores[:limit]:
            h = Hit(pid, sc, sorted(via[pid]))
            if pid in best_passage:
                p = self.passages[best_passage[pid][1]]
                h.passage_uid, h.passage_text, h.passage_section, h.passage_label = p["uid"], p["text"], p["section"], p["label"]
            hits.append(h)
        return hits


_SIG = None


def _signature(conn):
    r = conn.execute("SELECT (SELECT count(*) FROM claims) c, (SELECT coalesce(max(id),0) FROM claims) m, (SELECT count(*) FROM passages) p, "
                     "(SELECT count(*) FROM embeddings) e, (SELECT count(*) FROM papers) n").fetchone()
    return tuple(r.values())


def get_index(rebuild: bool = False) -> Index:
    """In-memory index, rebuilt automatically when claims, passages, embeddings or papers change."""
    global _INDEX, _SIG
    with _lock:
        with connect() as c:
            sig = _signature(c)
            if _INDEX is None or rebuild or sig != _SIG:
                _INDEX, _SIG = Index(c), sig
        return _INDEX


def snippet(text: str, query: str, width: int = 260) -> str:
    """Window of `text` around the densest cluster of query terms, with matches wrapped in «».."""
    import re
    terms = {t for t in tokenize(query)}
    if "vitd" in terms:
        terms.add("vitamin")                                          # 'vitamin D' is one token in the index; highlight its visible word
    words = list(re.finditer(r"\S+", text))
    if not words:
        return ""
    hit_idx = [i for i, m in enumerate(words) if any(tk in tokenize(m.group())[:3] for tk in terms)]
    centre = hit_idx[len(hit_idx) // 2] if hit_idx else 0
    start = max(0, words[centre].start() - width // 2)
    end = min(len(text), start + width)
    seg = text[start:end]
    out = re.sub(r"\S+", lambda m: f"«{m.group()}»" if any(tk in tokenize(m.group())[:3] for tk in terms) else m.group(), seg)
    return ("…" if start else "") + out + ("…" if end < len(text) else "")
