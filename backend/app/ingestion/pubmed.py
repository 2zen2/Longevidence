"""NCBI E-utilities client + PubMed XML parser."""
import re
from dataclasses import dataclass, field
from datetime import date

from lxml import etree

from ..config import settings
from .http import ApiClient
from .normalize import norm_doi, norm_pmcid, norm_pmid

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass
class PubMedRecord:
    pmid: str
    title: str
    abstract_text: str | None            # canonical text quotes point into
    sections: list[dict]                 # [{label, start, end}] offsets into abstract_text
    journal: str | None
    publication_date: date | None
    date_precision: str                  # year | month | day | none
    publication_types: list[str]
    mesh: list[str]
    doi: str | None
    pmcid: str | None
    flags: list[str] = field(default_factory=list)   # no_abstract, retracted, has_correction ...


def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _parse_date(article) -> tuple[date | None, str]:
    pd = article.find("Journal/JournalIssue/PubDate")
    if pd is not None:
        y = pd.findtext("Year")
        if not y and pd.findtext("MedlineDate"):
            m = re.search(r"(\d{4})", pd.findtext("MedlineDate"))
            y = m.group(1) if m else None
        if y:
            mo = pd.findtext("Month")
            d = pd.findtext("Day")
            month = None
            if mo:
                month = int(mo) if mo.isdigit() else MONTHS.get(mo[:3].lower())
            try:
                if month and d and d.isdigit():
                    return date(int(y), month, int(d)), "day"
                if month:
                    return date(int(y), month, 1), "month"
                return date(int(y), 1, 1), "year"
            except ValueError:
                return date(int(y), 1, 1), "year"
    ad = article.find("ArticleDate")
    if ad is not None and ad.findtext("Year"):
        try:
            return date(int(ad.findtext("Year")), int(ad.findtext("Month") or 1), int(ad.findtext("Day") or 1)), "day"
        except ValueError:
            pass
    return None, "none"


def build_abstract(article) -> tuple[str | None, list[dict]]:
    """Join AbstractText elements keeping section labels; return text and section offsets.

    Format: "LABEL: body" lines joined by newline. Offsets let us tell which section a quote is in.
    """
    parts = article.findall("Abstract/AbstractText")
    if not parts:
        return None, []
    text, sections = "", []
    for p in parts:
        label = (p.get("Label") or "").strip() or None
        body = _text(p)
        if not body:
            continue
        line = f"{label}: {body}" if label else body
        if text:
            text += "\n"
        start = len(text)
        text += line
        sections.append({"label": label or "ABSTRACT", "start": start, "end": len(text)})
    return (text or None), sections


def parse_efetch(xml_bytes: bytes) -> list[PubMedRecord]:
    root = etree.fromstring(xml_bytes)
    out = []
    for art in root.findall("PubmedArticle"):
        mc = art.find("MedlineCitation")
        article = mc.find("Article")
        pmid = norm_pmid(mc.findtext("PMID"))
        if not pmid or article is None:
            continue
        abstract, sections = build_abstract(article)
        d, precision = _parse_date(article)
        ids = {i.get("IdType"): _text(i) for i in art.findall("PubmedData/ArticleIdList/ArticleId")}
        doi = norm_doi(ids.get("doi"))
        if not doi:  # fall back to ELocationID
            for el in article.findall("ELocationID"):
                if el.get("EIdType") == "doi":
                    doi = norm_doi(_text(el))
        pubtypes = [_text(p) for p in article.findall("PublicationTypeList/PublicationType")]
        flags = []
        if not abstract:
            flags.append("no_abstract")
        for cc in mc.findall("CommentsCorrectionsList/CommentsCorrections"):
            rt = cc.get("RefType")
            if rt == "RetractionIn":
                flags.append("retracted")
            elif rt in ("ErratumIn", "CorrectedandRepublishedIn"):
                flags.append("has_correction")
        if "Retracted Publication" in pubtypes and "retracted" not in flags:
            flags.append("retracted")
        out.append(PubMedRecord(
            pmid=pmid, title=_text(article.find("ArticleTitle")), abstract_text=abstract, sections=sections,
            journal=_text(article.find("Journal/Title")) or None, publication_date=d, date_precision=precision,
            publication_types=pubtypes,
            mesh=[_text(m) for m in mc.findall("MeshHeadingList/MeshHeading/DescriptorName")],
            doi=doi, pmcid=norm_pmcid(ids.get("pmc")), flags=flags,
        ))
    return out


class PubMedClient:
    def __init__(self, api: ApiClient | None = None):
        rate = 10 if settings.ncbi_api_key else 3
        self.api = api or ApiClient(EUTILS, rate)

    def _params(self, **kw):
        p = {"tool": "longevidence", "email": settings.ncbi_email, **kw}
        if settings.ncbi_api_key:
            p["api_key"] = settings.ncbi_api_key
        return p

    def search(self, query: str, retmax: int = 30, sort: str = "pub_date") -> tuple[list[str], int]:
        """Returns (pmids, newest first (pub_date sort is stable; PubMed relevance ranking is not), total hit count)."""
        r = self.api.get("/esearch.fcgi", self._params(db="pubmed", term=query, retmax=retmax,
                                                       retmode="json", sort=sort))
        r.raise_for_status()
        res = r.json()["esearchresult"]
        return res["idlist"], int(res["count"])

    def fetch(self, pmids: list[str], batch: int = 50) -> list[PubMedRecord]:
        out = []
        for i in range(0, len(pmids), batch):
            chunk = pmids[i:i + batch]
            r = self.api.get("/efetch.fcgi", self._params(db="pubmed", id=",".join(chunk), retmode="xml"))
            r.raise_for_status()
            out.extend(parse_efetch(r.content))
        return out
