"""Topic -> PubMed query. One cheap model call proposes a query; code checks it and falls back to a plain keyword query.

The model never decides what is evidence: it only proposes search terms, which the user sees (and can edit) before anything is ingested."""
import re

from ..extraction.llm import LLMClient, LLMFatalError
from .normalize import sha256
from .pubmed import PubMedClient

PLAN_VERSION = "plan-v1"
MAX_QUERY_CHARS = 800
STOP = set("a an the of in on for to and or with without does do is are be by at as from vs versus what how can your you i my".split())

SYSTEM = """You turn a health or medical topic into one PubMed search query.

Rules:
1. Identify the 2-3 core concepts (for example an exposure and an outcome). Join concepts with AND.
2. Within a concept, join synonyms, plural forms and the MeSH heading with OR. Use [Title/Abstract] for free-text terms and [MeSH Terms] for MeSH headings. Quote multi-word phrases.
3. Do not add date, language, species or publication-type filters unless the topic itself asks for them. Always end with AND hasabstract[text].
4. Keep it under 600 characters. Return the query only, plus a one-sentence rationale a non-expert can read."""

SCHEMA = {"type": "object", "properties": {"query": {"type": "string", "description": "PubMed query string"},
                                           "rationale": {"type": "string"}}, "required": ["query"]}


def fallback_query(topic: str) -> str:
    words = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9+-]*", topic):
        if w.lower() not in STOP and len(w) > 2 and w.lower() not in words:
            words.append(w.lower())
    words = words[:6]
    if not words:
        raise ValueError("topic has no searchable words")
    return "(" + " AND ".join(f"{w}[Title/Abstract]" for w in words) + ") AND hasabstract[text]"


def valid_query(q: str) -> bool:
    q = q.strip()
    if not q or len(q) > MAX_QUERY_CHARS or q.count('"') % 2:
        return False
    depth = 0
    for ch in q:
        depth += ch == "("
        depth -= ch == ")"
        if depth < 0:
            return False
    return depth == 0 and bool(re.search(r"[A-Za-z]{3}", q))


def plan_query(topic: str, client: LLMClient, pubmed: PubMedClient | None = None) -> dict:
    """{'query','rationale','source': 'model'|'keywords','count'}; count is how many PubMed records the query matches."""
    topic = " ".join(topic.split())
    pubmed = pubmed or PubMedClient()
    query = rationale = None
    try:
        resp = client.complete(sha256(topic, client.model, PLAN_VERSION), SYSTEM, f"Topic: {topic}", SCHEMA)
        cand = " ".join(str(resp.output.get("query") or "").split())
        if valid_query(cand):
            query, rationale = cand, str(resp.output.get("rationale") or "")[:400] or None
    except LLMFatalError:
        raise                        # bad key / quota: the user must hear about it, not get a silent keyword search
    except Exception:
        pass                         # one bad model answer is not fatal: use the keyword query
    source = "model"
    count = pubmed.search(query, 1)[1] if query else 0
    if not query or count == 0:
        query, source, rationale = fallback_query(topic), "keywords", "Plain keyword search (the model's query was unusable or matched nothing)."
        count = pubmed.search(query, 1)[1]
    return {"topic": topic, "query": query, "rationale": rationale, "source": source, "count": count}
