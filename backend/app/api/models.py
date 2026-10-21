from datetime import date

from pydantic import BaseModel


class IdentifierOut(BaseModel):
    source: str
    type: str
    value: str
    url: str | None = None


class PaperDetail(BaseModel):
    id: int
    title: str
    journal: str | None
    publication_date: date | None
    publication_types: list[str]
    identifiers: list[IdentifierOut]


class QuestionBrief(BaseModel):
    id: int
    label: str
    question: str
    slug: str | None = None
    tags: list[str] = []
    aliases: list[str] = []


class KeyFinding(BaseModel):
    outcome: str
    direction: str
    estimate: str                  # e.g. "HR 0.86 (95% CI 0.68 to 1.08) p = 0.2"
    quote: str | None = None
    verification: str


class MatchInfo(BaseModel):
    via: list[str]                 # keyword | semantic
    score: float
    passage_uid: str | None = None
    passage_where: str | None = None   # e.g. 'Full text · Results'


class PaperCard(BaseModel):
    id: int
    title: str
    journal: str | None
    year: int | None
    design: str                    # rct | rct_secondary_analysis | cohort | meta_analysis | cross_sectional | other | unknown
    design_source: str             # 'extracted' (LLM, verified) | 'pubmed' (publication-type metadata)
    sample_size: int | float | str | None = None
    population: str | None = None
    intervention: str | None = None
    comparator: str | None = None
    key_finding: KeyFinding | None = None
    verified_fraction: float | None = None
    extracted: bool
    model: str | None = None
    pmid: str | None = None
    doi: str | None = None
    cited_by: int | None = None
    open_access_url: str | None = None
    topics: list[int] = []
    snippet: str | None = None
    match: MatchInfo | None = None


class Summary(BaseModel):
    n_papers: int
    n_extracted: int
    n_with_finding: int
    directions: dict[str, int]
    by_design: dict[str, dict[str, int]]


class Facets(BaseModel):
    design: dict[str, int]
    year_min: int | None
    year_max: int | None


class SearchResponse(BaseModel):
    query: str
    topic: int | None
    topic_question: str | None
    match_mode: str                # and | or | browse
    total: int
    facets: Facets
    summary: Summary
    cards: list[PaperCard]
