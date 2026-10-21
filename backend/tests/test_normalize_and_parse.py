from datetime import date

from app.ingestion.normalize import norm_doi, norm_openalex_id, norm_pmcid, norm_pmid
from app.ingestion.pubmed import parse_efetch


def test_identifier_normalization():
    assert norm_doi("https://doi.org/10.1000/ABC.1") == "10.1000/abc.1"
    assert norm_doi("doi: 10.1/X") == "10.1/x"
    assert norm_doi("not-a-doi") is None
    assert norm_pmid("PMID: 123") == "123" and norm_pmid("12a") is None
    assert norm_pmcid("pmc123") == "PMC123" and norm_pmcid("123") == "PMC123"
    assert norm_openalex_id("https://openalex.org/w42") == "W42"


def test_parse_structured_abstract_and_ids(efetch_xml):
    recs = {r.pmid: r for r in parse_efetch(efetch_xml)}
    r = recs["111"]
    assert r.title == "Drug X in heart failure: a randomized trial."      # inline <i> flattened
    assert r.doi == "10.1000/abc.1" and r.pmcid == "PMC999"
    assert r.publication_date == date(2024, 3, 5) and r.date_precision == "day"
    assert "Randomized Controlled Trial" in r.publication_types
    assert [s["label"] for s in r.sections] == ["BACKGROUND", "RESULTS"]
    s = r.sections[1]
    assert r.abstract_text[s["start"]:s["end"]].startswith("RESULTS: We randomized 200")
    assert r.mesh == ["Heart Failure"]


def test_parse_edge_cases(efetch_xml):
    recs = {r.pmid: r for r in parse_efetch(efetch_xml)}
    r2 = recs["222"]
    assert r2.abstract_text is None and "no_abstract" in r2.flags and "retracted" in r2.flags
    assert r2.publication_date == date(2023, 1, 1) and r2.date_precision == "year"   # MedlineDate
    r3 = recs["333"]
    assert r3.sections[0]["label"] == "ABSTRACT" and r3.publication_date == date(2022, 1, 1)
