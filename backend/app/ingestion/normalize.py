"""Identifier normalization. Every identifier is normalized before it is stored or compared."""
import hashlib
import re
import unicodedata

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)


def norm_doi(v: str | None) -> str | None:
    if not v:
        return None
    v = _DOI_PREFIX.sub("", v.strip()).strip().lower()
    return v if v.startswith("10.") else None


def norm_pmid(v: str | None) -> str | None:
    if not v:
        return None
    v = re.sub(r"^pmid:?\s*", "", str(v).strip(), flags=re.I)
    return v if v.isdigit() else None


def norm_pmcid(v: str | None) -> str | None:
    if not v:
        return None
    m = re.search(r"(?:PMC)?(\d+)$", str(v).strip(), re.I)
    return f"PMC{m.group(1)}" if m else None


def norm_openalex_id(v: str | None) -> str | None:
    if not v:
        return None
    m = re.search(r"(W\d+)$", v.strip(), re.I)
    return m.group(1).upper() if m else None


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip().lower()


def sha256(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()
