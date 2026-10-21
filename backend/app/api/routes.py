import json

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..db import connect
from .models import IdentifierOut, PaperDetail, QuestionBrief

router = APIRouter(prefix="/api")

IDENT_URL = {("pubmed", "pmid"): "https://pubmed.ncbi.nlm.nih.gov/{}/", ("pubmed", "doi"): "https://doi.org/{}",
             ("pubmed", "pmc"): "https://www.ncbi.nlm.nih.gov/pmc/articles/{}/",
             ("openalex", "openalex_id"): "https://openalex.org/{}", ("openalex", "doi"): "https://doi.org/{}"}


def _presets() -> dict[str, dict]:
    try:
        return {q["query"]: q for q in json.loads((settings.data_dir / "questions.json").read_text())}
    except FileNotFoundError:
        return {}


@router.get("/questions", response_model=list[QuestionBrief], tags=["Corpus"], summary="List the research questions in the corpus")
def questions():
    presets = _presets()
    with connect() as c:
        rows = c.execute("SELECT id, question, query FROM research_questions ORDER BY id").fetchall()
    return [QuestionBrief(id=r["id"], label=presets.get(r["query"], {}).get("label", r["question"][:30]), question=r["question"],
                          slug=presets.get(r["query"], {}).get("slug"), tags=presets.get(r["query"], {}).get("tags", []), aliases=presets.get(r["query"], {}).get("aliases", [])) for r in rows]


@router.get("/papers/{paper_id}", response_model=PaperDetail, tags=["Corpus"], summary="Paper metadata and source links")
def paper(paper_id: int):
    with connect() as c:
        r = c.execute(
            "SELECT p.id, p.title, p.journal, p.publication_date, p.source_metadata, "
            "(SELECT jsonb_agg(jsonb_build_object('source',source,'type',identifier_type,'value',identifier_value) ORDER BY id) "
            " FROM paper_identifiers WHERE paper_id=p.id) AS idents FROM papers p WHERE p.id=%s", (paper_id,)).fetchone()
    if not r:
        raise HTTPException(404, "paper not found")
    return PaperDetail(
        id=r["id"], title=r["title"], journal=r["journal"], publication_date=r["publication_date"],
        publication_types=((r["source_metadata"] or {}).get("pubmed") or {}).get("publication_types", []),
        identifiers=[IdentifierOut(source=i["source"], type=i["type"], value=i["value"],
                                   url=(IDENT_URL.get((i["source"], i["type"])) or "").format(i["value"]) or None)
                     for i in (r["idents"] or [])])
