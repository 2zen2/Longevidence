"""Corpus search + evidence summary.

The corpus is a few hundred papers, so candidate rows are fetched with one query and filtering, faceting and the
summary are done in Python. (At thousands of papers these would move into SQL.)

Evidence summary honesty rules: only findings whose quote verified (exact/fuzzy) are counted; the count is a *vote count* of extracted
directions, not a pooled effect, and the response says how many papers it covers."""
import re
from collections import Counter

from fastapi import APIRouter, Query

from ..db import connect
from .models import Facets, KeyFinding, MatchInfo, PaperCard, SearchResponse, Summary

router = APIRouter(prefix="/api")

DESIGN_FROM_PUBMED = [("Meta-Analysis", "meta_analysis"), ("Systematic Review", "meta_analysis"),
                      ("Randomized Controlled Trial", "rct"), ("Observational Study", "cohort"),
                      ("Review", "other")]
STOP = set("a an the of in on for to and or with without does do is are be by at as from vs versus what how can".split())
FTS = "to_tsvector('english', coalesce(p.title,'') || ' ' || coalesce(p.abstract,''))"

CARD_SQL = f"""
SELECT p.id, p.title, p.journal, p.publication_date, p.source_metadata,
  (SELECT jsonb_agg(jsonb_build_object('type',identifier_type,'value',identifier_value) ORDER BY id)
     FROM paper_identifiers WHERE paper_id=p.id) AS idents,
  (SELECT array_agg(DISTINCT qp.question_id) FROM question_papers qp WHERE qp.paper_id=p.id) AS topics,
  e.output->'extraction' AS ex, e.model_name,
  {{rank}} AS rank, {{snippet}} AS snippet
FROM papers p
LEFT JOIN LATERAL (SELECT output, model_name FROM extraction_runs
                   WHERE paper_id=p.id AND status='ok' ORDER BY created_at DESC LIMIT 1) e ON true
{{where}}
"""


def _terms(q: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9-]+", q.lower()) if w not in STOP and len(w) > 2]


def _design(ex: dict | None, pubtypes: list[str]) -> tuple[str, str]:
    d = ((ex or {}).get("study") or {}).get("design") or {}
    if d.get("status") == "reported" and d.get("value"):
        return d["value"], "extracted"
    for key, val in DESIGN_FROM_PUBMED:
        if key in pubtypes:
            return val, "pubmed"
    return "unknown", "pubmed"


def _fmt(f: dict) -> str:
    parts = []
    if f.get("effect_value") is not None:
        parts.append(f"{f.get('effect_measure') or 'effect'} {f['effect_value']:g}")
    if f.get("ci_low") is not None and f.get("ci_high") is not None:
        parts.append(f"(95% CI {f['ci_low']:g} to {f['ci_high']:g})")
    if f.get("p_value") is not None:
        parts.append(f"p = {f['p_value']:g}")
    return " ".join(parts)


_GENERIC_OUTCOME = {"change", "changes", "effect", "effects", "outcome", "outcomes", "total", "level", "levels", "risk", "rate", "rates", "incidence", "measure", "score"}


def _relevant(outcome: str, query: str, qvec=None) -> bool:
    """Does a finding's outcome match the search: a shared word (after stemming and the synonym table) or, failing that, a close meaning."""
    from ..search.bm25 import tokenize
    from ..search.synonyms import expand
    q = set(tokenize(query))
    qx = set().union(*(expand(t) for t in q)) if q else set()
    toks = [t for t in tokenize(outcome.lower()) if t not in _GENERIC_OUTCOME and len(t) > 2]
    if any(expand(t) & qx for t in toks):
        return True
    if qvec is not None and outcome.strip():
        from ..search.embed import embed_docs
        return float(embed_docs([outcome])[0] @ qvec) >= 0.68
    return False


def _key_finding(ex: dict | None, query: str = "", qvec=None) -> KeyFinding | None:
    """First finding whose quote verified, preferring one with a numeric estimate. With a search query, only a finding on what was searched for."""
    ok = [f for f in ((ex or {}).get("primary_findings") or []) if f.get("verification") in ("exact", "fuzzy")]
    if query.strip():
        ok = [f for f in ok if _relevant(f.get("outcome") or "", query, qvec)]
    if not ok:
        return None
    f = next((x for x in ok if x.get("effect_value") is not None), ok[0])
    return KeyFinding(outcome=f.get("outcome") or "", direction=f.get("direction") or "unclear", estimate=_fmt(f),
                      quote=f.get("quote"), verification=f["verification"])


def _card(r: dict, query: str = "", qvec=None) -> PaperCard:
    meta = r["source_metadata"] or {}
    pubtypes = (meta.get("pubmed") or {}).get("publication_types", [])
    ex = r["ex"]
    study = (ex or {}).get("study") or {}
    design, design_src = _design(ex, pubtypes)
    val = lambda k: (study.get(k) or {}).get("value") if (study.get(k) or {}).get("status") == "reported" else None
    ids = {i["type"]: i["value"] for i in (r["idents"] or [])}
    oa = meta.get("openalex") or {}
    claims = ([(study.get(k) or {}) for k in ("design", "population", "sample_size", "intervention", "comparator", "follow_up")]
              + list((ex or {}).get("primary_findings") or []))
    claims = [c for c in claims if c.get("status", "reported") == "reported" and (c.get("value") is not None or c.get("outcome"))]
    ver = [c.get("verification") in ("exact", "fuzzy") for c in claims]
    return PaperCard(
        id=r["id"], title=r["title"], journal=r["journal"], year=r["publication_date"].year if r["publication_date"] else None,
        design=design, design_source=design_src, sample_size=val("sample_size"), population=val("population"),
        intervention=val("intervention"), comparator=val("comparator"), key_finding=_key_finding(ex, query, qvec),
        verified_fraction=(sum(ver) / len(ver)) if ver else None, extracted=ex is not None, model=r["model_name"],
        pmid=ids.get("pmid"), doi=ids.get("doi"), cited_by=oa.get("cited_by_count"), open_access_url=oa.get("oa_url"),
        topics=list(r["topics"] or []), snippet=r.get("snippet"))


def summarize(cards: list[PaperCard]) -> Summary:
    dirs, by_design = Counter(), {}
    n_find = 0
    for c in cards:
        if c.key_finding:
            n_find += 1
            d = c.key_finding.direction
            d = d if d in ("favors_intervention", "no_difference", "favors_comparator") else "unclear"
            dirs[d] += 1
            by_design.setdefault(c.design, Counter())[d] += 1
    return Summary(n_papers=len(cards), n_extracted=sum(c.extracted for c in cards), n_with_finding=n_find,
                   directions={k: dirs.get(k, 0) for k in ("favors_intervention", "no_difference", "favors_comparator", "unclear")},
                   by_design={k: dict(v) for k, v in by_design.items()})


@router.get("/search", response_model=SearchResponse, tags=["Corpus"], summary="Search the paper corpus")
def search(q: str = Query("", description="Free-text query. Leave empty to browse newest first.", examples=["cold water immersion muscle"]),
           topic: int | None = Query(None, description="Restrict to one research question (id from /api/questions)."),
           design: str | None = Query(None, description="Study design filter, e.g. rct, meta_analysis, cohort."),
           year_min: int | None = Query(None, description="Earliest publication year."),
           min_n: int | None = Query(None, description="Minimum sample size."),
           fulltext: bool = Query(False, description="Only papers with stored open-access full text."),
           verified_only: bool = Query(False, description="Only papers with a quote-verified finding."),
           how: str = Query("hybrid", pattern="^(hybrid|keyword|semantic)$", description="Retrieval mode."),
           limit: int = Query(50, ge=1, le=200), offset: int = 0):
    """With a query: hybrid retrieval (BM25 keyword + vector similarity, fused by RRF) over titles, abstracts and full-text passages, filtered by the
    metadata index (design, year, sample size, full-text availability). Without a query: browse newest first."""
    from ..search.index import get_index, snippet
    with connect() as c:
        topics = {r["id"]: r["question"] for r in c.execute("SELECT id, question FROM research_questions")}
        topic_ids = {r["paper_id"] for r in c.execute("SELECT paper_id FROM question_papers WHERE question_id=%s", (topic,))} if topic is not None else None
        idx = get_index()
        allowed = idx.allowed(None, year_min, min_n, fulltext, topic_ids)           # every filter except design, so design facets stay informative
        hits = []
        if q.strip():
            hits = idx.search(q, how, allowed, limit=200)
            ids = [h.paper_id for h in hits]
        else:
            ids = [i for i, _ in sorted(((i, idx.meta[i]["year"] or 0) for i in allowed), key=lambda x: -x[1])]
        facet = Counter((idx.meta[i]["design"] or "unknown") for i in ids)
        if design:
            hits = [h for h in hits if (idx.meta[h.paper_id]["design"] or "unknown") == design]
            ids = [i for i in ids if (idx.meta[i]["design"] or "unknown") == design]
        if verified_only:
            ids = [i for i in ids if idx.meta[i]["verified_findings"]]
            hits = [h for h in hits if h.paper_id in set(ids)]
        total = len(ids)
        page = ids[offset:offset + limit]
        rows = {r["id"]: r for r in c.execute(CARD_SQL.format(rank="0", snippet="NULL", where="WHERE p.id = ANY(%s)"), (page,)).fetchall()} if page else {}
    by_id = {h.paper_id: h for h in hits}
    qvec = None
    if q.strip():
        from ..search.embed import embed_query
        try:
            qvec = embed_query(q)
        except Exception:
            qvec = None
    cards = []
    for i in page:
        if i not in rows:
            continue
        card = _card(rows[i], q, qvec)
        m = idx.meta[i]
        if m["design"]:
            card.design = m["design"]
        h = by_id.get(i)
        if h:
            where = None
            if h.passage_text:
                where = f"Full text · {h.passage_label or (h.passage_section or '').title()}"
                card.snippet = snippet(h.passage_text, q)
            elif idx.papers[i]["abstract"]:
                card.snippet = snippet(idx.papers[i]["abstract"], q)
            card.match = MatchInfo(via=h.via, score=round(h.score, 4), passage_uid=h.passage_uid, passage_where=where)
        cards.append(card)
    years = [x.year for x in cards if x.year]
    return SearchResponse(
        query=q, topic=topic, topic_question=topics.get(topic) if topic else None, match_mode=how if q.strip() else "browse", total=total,
        facets=Facets(design=dict(facet), year_min=min(years) if years else None, year_max=max(years) if years else None),
        summary=summarize(cards), cards=cards)
