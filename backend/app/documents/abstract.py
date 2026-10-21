"""PubMed abstract -> document. Offsets equal the offsets already used by the extraction verifier, because the
document text *is* source_texts.text (passages are its labelled sections)."""
from .model import ParsedDocument, ParsedPassage, canonical_section, sha256

PARSER = "abstract-1"


def parse_abstract(text: str, sections: list[dict]) -> ParsedDocument:
    passages = []
    spans = sections or [{"label": "ABSTRACT", "start": 0, "end": len(text)}]
    for i, s in enumerate(spans):
        t = text[s["start"]:s["end"]]
        passages.append(ParsedPassage(text=t, section=canonical_section(s["label"], inherited="other"), kind="abstract_section",
                                      section_title=s["label"].title(), start=s["start"], end=s["end"]))
    # Offsets are taken from the stored sections, not recomputed, so quote offsets from extraction stay valid.
    return ParsedDocument(kind="pubmed_abstract", parser_version=PARSER, passages=passages, text=text, text_hash=sha256(text))
