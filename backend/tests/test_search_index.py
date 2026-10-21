"""Keyword (BM25), vector and metadata indexes, and their fusion. The embedding model is replaced by hand-made vectors."""
import numpy as np

from app.search import index as ix
from app.search.bm25 import BM25, stem, tokenize
from app.search.index import Index, snippet

DOCS = {1: "Vitamin D supplementation and fracture risk in older adults",
        2: "SGLT2 inhibitors reduce heart failure hospitalization",
        3: "Time-restricted eating and body weight in obesity",
        4: "Bone mineral density after sunlight exposure"}


def test_stemming_matches_inflections():
    assert stem("fracture") == stem("fractures") == stem("fractured")
    assert tokenize("SGLT2") == ["sglt2"]                      # alphanumeric terms are kept exact


def test_bm25_exact_terms_and_title_boost():
    b = BM25({1: "fractures were counted", 2: "bone density measured"}, field_boost={2: "fractures"}, boost=3)
    assert b.search("fracture")[0][0] == 2                # title hit outweighs one body mention
    assert [i for i, _ in BM25(DOCS).search("SGLT2")] == [2]
    assert [i for i, _ in BM25(DOCS).search("time restricted")][0] == 3        # hyphenated term also matches its parts


def _index(vecs: dict[int, list[float]], meta: dict[int, dict]) -> Index:
    i = object.__new__(Index)
    i.papers = {k: {"id": k, "title": v, "abstract": ""} for k, v in DOCS.items()}
    i.passages = {}
    i.bm_papers = BM25(DOCS)
    i.bm_passages = BM25({})
    i.meta = meta
    ids = sorted(vecs)
    m = np.array([vecs[k] for k in ids], dtype=np.float32)
    i.vec_papers, i.ids_papers = m / np.linalg.norm(m, axis=1, keepdims=True), ids
    i.vec_passages, i.ids_passages = None, []
    return i


META = {1: {"design": "rct", "year": 2024, "sample_size": 3000, "fulltext": True, "verified_findings": 2},
        2: {"design": "rct", "year": 2026, "sample_size": 500, "fulltext": False, "verified_findings": 1},
        3: {"design": "cohort", "year": 2025, "sample_size": None, "fulltext": True, "verified_findings": 0},
        4: {"design": "meta_analysis", "year": 2023, "sample_size": 900, "fulltext": False, "verified_findings": 1}}
VECS = {1: [1, 0, 0], 2: [0, 1, 0], 3: [0, 0, 1], 4: [0.9, 0.1, 0]}      # 4 is semantically close to 1 but shares no words with the query


def test_hybrid_finds_a_paper_by_meaning_that_keywords_miss(monkeypatch):
    idx = _index(VECS, META)
    monkeypatch.setattr(Index, "_dense", lambda self, q: {"paper": [(1, 0.90), (4, 0.88), (2, 0.1)]})
    kw = idx.search("vitamin D fracture", "keyword")
    hy = idx.search("vitamin D fracture", "hybrid")
    assert [h.paper_id for h in kw] == [1]
    assert {h.paper_id for h in hy} == {1, 4}                  # paper 4 (cholecalciferol) found by the vector index only
    top = hy[0]
    assert top.paper_id == 1 and top.via == ["keyword", "semantic"]          # both indexes agree -> ranked first, tagged with both
    assert next(h for h in hy if h.paper_id == 4).via == ["semantic"]


def test_cosine_floor_drops_weak_semantic_matches(monkeypatch):
    idx = _index(VECS, META)
    monkeypatch.setattr(Index, "_dense", lambda self, q: {"paper": [(3, 0.2)]})
    assert idx.search("zzz", "semantic") == []


def test_metadata_filters_and_facets():
    idx = _index(VECS, META)
    assert idx.allowed(design="rct") == {1, 2}
    assert idx.allowed(year_min=2025) == {2, 3}
    assert idx.allowed(min_n=1000) == {1}
    assert idx.allowed(fulltext=True) == {1, 3}
    assert idx.allowed(design="rct", fulltext=True, min_n=1000) == {1}
    assert idx.allowed(topic_ids={4}) == {4}


def test_search_respects_allowed_set(monkeypatch):
    idx = _index(VECS, META)
    monkeypatch.setattr(Index, "_dense", lambda self, q: {"paper": [(1, 0.90), (4, 0.88)]})
    assert [h.paper_id for h in idx.search("vitamin D fracture", "hybrid", allowed={4})] == [4]


def test_snippet_highlights_query_terms():
    s = snippet("Higher doses of vitamin D reduced the number of hip fractures in the placebo-controlled trial.", "vitamin D fractures")
    assert "«vitamin»" in s and "«fractures»" in s


def test_dense_margin_drops_hits_far_below_the_best_cosine(monkeypatch):
    idx = _index(VECS, META)
    monkeypatch.setattr(Index, "_dense", lambda self, q: {"paper": [(1, 0.90), (4, 0.70)]})
    assert [h.paper_id for h in idx.search("zzz", "semantic")] == [1]            # 0.70 is above the floor but 0.20 below the best
