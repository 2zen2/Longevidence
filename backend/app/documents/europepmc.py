"""Europe PMC open-access full text (JATS). Legal basis: only articles Europe PMC itself serves as open-access XML are fetched;
the license string found in the XML is stored with the document. Nothing is scraped from publisher sites."""
from pathlib import Path

from ..config import settings
from ..ingestion.http import ApiClient
from .model import sha256

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


class EuropePMC:
    def __init__(self, client: ApiClient | None = None):
        self.api = client or ApiClient(BASE, per_second=5)

    def fulltext_xml(self, pmcid: str) -> bytes | None:
        r = self.api.get(f"/{pmcid}/fullTextXML")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise RuntimeError(f"Europe PMC HTTP {r.status_code}")
        return r.content if b"<article" in r.content[:2000] or b"<article" in r.content else None


def save_raw(paper_id: int, xml: bytes) -> tuple[str, str]:
    """Keep the original file exactly as received. Returns (path relative to data_dir, sha256)."""
    digest = sha256(xml)
    rel = Path("sources") / str(paper_id) / f"pmc_{digest[:12]}.xml"
    dest = settings.data_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(xml)
    return str(rel), digest
