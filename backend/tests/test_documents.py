"""JATS parsing: structure, offsets, stable ids. Offsets must always index the stored document text."""
from pathlib import Path

from app.documents.abstract import parse_abstract
from app.documents.jats import parse_jats
from app.documents.model import canonical_section, passage_uid

XML = (Path(__file__).parent / "fixtures" / "sample_jats.xml").read_bytes()


def test_offsets_index_document_text():
    doc = parse_jats(XML)
    assert doc.passages
    for p in doc.passages:
        assert doc.text[p.start:p.end] == p.text


def test_sections_inherit_from_major_heading():
    sec = lambda start: next(p.section for p in parse_jats(XML).passages if p.text.startswith(start))
    assert sec("We randomized 200") == "results"          # 'Study population' must not become methods
    assert sec("This was a randomized") == "methods"
    assert sec("Limitations include") == "discussion"


def test_reference_callouts_and_reference_list_are_dropped():
    doc = parse_jats(XML)
    intro = next(p for p in doc.passages if p.text.startswith("Heart failure is common"))
    assert "common and costly" in intro.text            # '1' callout removed, no fused digits
    assert not any("Ref text" in p.text for p in doc.passages)


def test_table_is_flattened_with_spacing_and_kept_structured():
    t = next(p for p in parse_jats(XML).passages if p.kind == "table")
    assert t.label == "Table 1" and "Drug X n = 100" in t.text and "Age | 61 (55–70)" in t.text
    assert t.table_json["rows"] == [["Age", "61 (55–70)"]]


def test_figure_caption_and_funding_and_license_and_pages():
    doc = parse_jats(XML)
    cap = next(p for p in doc.passages if p.kind == "figure_caption")
    assert cap.text == "Fig. 1. Survival. Kaplan-Meier curves for the primary outcome."
    fund = [p for p in doc.passages if p.section == "funding_coi"]
    assert any("National Heart Institute" in p.text and "doi.org" not in p.text for p in fund)
    assert any("thank the trial participants" in p.text for p in fund)
    assert doc.license == "https://creativecommons.org/licenses/by/4.0/" and doc.printed_pages == "101-109"


def test_passage_uid_is_content_derived_and_stable():
    a, b = parse_jats(XML), parse_jats(XML)
    assert [passage_uid(a.text_hash, p.start, p.end) for p in a.passages] == [passage_uid(b.text_hash, p.start, p.end) for p in b.passages]
    assert passage_uid("h1", 0, 5) != passage_uid("h2", 0, 5)


def test_abstract_passages_keep_extractor_offsets():
    text = "BACKGROUND: a b c.\nRESULTS: x y z."
    doc = parse_abstract(text, [{"label": "BACKGROUND", "start": 0, "end": 18}, {"label": "RESULTS", "start": 19, "end": 34}])
    assert [(p.start, p.end, p.section) for p in doc.passages] == [(0, 18, "background"), (19, 34, "results")]
    assert doc.text == text


def test_canonical_section():
    assert canonical_section("Statistical analysis") == "methods"
    assert canonical_section("Safety outcomes", inherited="results") == "results"
    assert canonical_section("Competing interests") == "funding_coi"
    assert canonical_section("ABSTRACT") == "abstract"
