"""OpenAlex client: second source used to demonstrate cross-source identifier resolution."""
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..config import settings
from .http import ApiClient
from .normalize import norm_doi, norm_openalex_id, norm_pmid, norm_text


@dataclass
class OpenAlexWork:
    openalex_id: str
    doi: str | None
    pmid: str | None
    title: str | None
    year: int | None
    cited_by_count: int
    is_oa: bool | None
    oa_status: str | None
    oa_url: str | None
    work_type: str | None
    is_retracted: bool | None


def parse_work(j: dict) -> OpenAlexWork:
    oa = j.get("open_access") or {}
    return OpenAlexWork(
        openalex_id=norm_openalex_id(j["id"]),
        doi=norm_doi(j.get("doi")),
        pmid=norm_pmid((j.get("ids") or {}).get("pmid", "").rsplit("/", 1)[-1]),
        title=j.get("title") or j.get("display_name"),
        year=j.get("publication_year"),
        cited_by_count=j.get("cited_by_count") or 0,
        is_oa=oa.get("is_oa"), oa_status=oa.get("oa_status"), oa_url=oa.get("oa_url"),
        work_type=j.get("type"), is_retracted=j.get("is_retracted"),
    )


class OpenAlexClient:
    def __init__(self, api: ApiClient | None = None):
        self.api = api or ApiClient("https://api.openalex.org", 8)

    def get_by(self, pmid: str | None, doi: str | None) -> OpenAlexWork | None:
        """Resolve by PMID first, then DOI. 404 means 'not in OpenAlex' (not an error)."""
        for key in (f"pmid:{pmid}" if pmid else None, f"doi:{doi}" if doi else None):
            if not key:
                continue
            r = self.api.get(f"/works/{key}", {"mailto": settings.openalex_mailto})
            if r.status_code == 404:
                continue
            r.raise_for_status()
            return parse_work(r.json())
        return None


def reconcile(pubmed_title: str, pubmed_year: int | None, pubmed_doi: str | None, w: OpenAlexWork) -> dict:
    """Cross-source agreement checks. Disagreements are recorded and surfaced, never auto-resolved."""
    sim = fuzz.token_set_ratio(norm_text(pubmed_title), norm_text(w.title or "")) if w.title else None
    issues = []
    doi_match = None
    if pubmed_doi and w.doi:
        doi_match = pubmed_doi == w.doi
        if not doi_match:
            issues.append("doi_mismatch")
    if sim is not None and sim < 85:
        issues.append("title_mismatch")
    if pubmed_year and w.year and abs(pubmed_year - w.year) > 1:
        issues.append("year_mismatch")
    if w.is_retracted:
        issues.append("openalex_retracted")
    return {"doi_match": doi_match, "title_similarity": sim, "year_pubmed": pubmed_year,
            "year_openalex": w.year, "issues": issues}
