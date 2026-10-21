"""Parsed-document model shared by every source parser (abstract, JATS full text, later PDF).

A parser returns ParsedPassage objects *without* offsets; `assemble` joins them into the normalized document text and
fills start/end so the offsets are always consistent with the text that is stored and hashed."""
import hashlib
import re
from dataclasses import dataclass, field

SEPARATOR = "\n\n"
_WS = re.compile(r"\s+")

# Canonical section vocabulary used by retrieval and assessment (the printed heading is kept separately).
SECTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("funding_coi", ("funding", "competing", "conflict", "disclos", "acknowledg", "financial", "sponsor", "author contribution")),
    ("conclusions", ("conclusion", "interpretation", "summary", "implication")),
    ("methods", ("method", "design", "setting", "participant", "patient", "procedure", "statistic", "outcome measure",
                 "randomi", "intervention", "material", "population", "study population", "trial")),
    ("results", ("result", "finding", "outcome", "efficacy", "safety", "adverse", "baseline", "subgroup", "sensitivity")),
    ("discussion", ("discussion", "limitation", "strength")),
    ("background", ("background", "introduction", "objective", "aim", "purpose", "rationale", "main", "context", "importance")),
]


MAJOR = {"background", "methods", "results", "discussion", "conclusions", "funding_coi", "abstract"}


def canonical_section(title: str | None, sec_type: str | None = None, inherited: str | None = None) -> str:
    """Map a printed heading to the canonical vocabulary.

    A subsection of Results stays 'results' even when its own heading looks like a methods word ("Study population"):
    once a major section is established, children inherit it."""
    if inherited in MAJOR:
        return inherited
    if (title or "").strip().lower() == "abstract":
        return "abstract"
    for text in (title or "", sec_type or ""):
        t = text.lower()
        if not t:
            continue
        for name, keys in SECTION_RULES:
            if any(k in t for k in keys):
                return name
    return inherited or "other"


def clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def passage_uid(doc_text_hash: str, start: int, end: int) -> str:
    """Content-derived and position-derived: re-parsing the same text yields the same ids, so citations survive re-runs."""
    return hashlib.sha1(f"{doc_text_hash}|{start}|{end}".encode()).hexdigest()[:12]


@dataclass
class ParsedPassage:
    text: str
    section: str
    kind: str                       # abstract_section | paragraph | table | figure_caption | note
    section_title: str | None = None
    label: str | None = None
    page_number: int | None = None
    printed_page: str | None = None
    table_json: dict | None = None
    start: int = 0
    end: int = 0


@dataclass
class ParsedDocument:
    kind: str
    parser_version: str
    passages: list[ParsedPassage]
    text: str = ""
    text_hash: str = ""
    printed_pages: str | None = None
    license: str | None = None
    meta: dict = field(default_factory=dict)


def assemble(kind: str, parser_version: str, passages: list[ParsedPassage], **kw) -> ParsedDocument:
    """Concatenate passages into the normalized document text and assign offsets."""
    parts, pos, kept = [], 0, []
    for p in passages:
        p.text = p.text.strip()
        if not p.text:
            continue
        if parts:
            pos += len(SEPARATOR)
        p.start, p.end = pos, pos + len(p.text)
        pos = p.end
        parts.append(p.text)
        kept.append(p)
    text = SEPARATOR.join(parts)
    return ParsedDocument(kind=kind, parser_version=parser_version, passages=kept, text=text, text_hash=sha256(text), **kw)
