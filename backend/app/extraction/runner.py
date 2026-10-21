"""Run one extraction: prompt -> validate -> (one repair retry) -> verify. Plus DB-backed caching."""
import json
import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..db import connect, jsonb
from ..ingestion.normalize import sha256
from .llm import LLMClient, LLMFatalError
from .prompts import PROMPT_VERSION, get_prompt, user_prompt
from .schema import SCHEMA_VERSION, PaperExtraction, tool_schema
from .verify import missing_quotes, verification_summary, verify_extraction

log = logging.getLogger("longevidence.extract")


@dataclass
class ExtractionResult:
    status: str                                  # ok | invalid | error
    extraction: PaperExtraction | None = None
    raw: dict | None = None                      # what the model said, before verification
    usage: dict = field(default_factory=dict)
    error: str | None = None
    attempts: int = 0
    served_model: str | None = None   # what the provider says actually answered (aliases like '-latest' move)


def coerce_output(out: dict) -> dict:
    """Some models double-encode nested values as JSON strings. Decode those; Pydantic still validates the result."""
    fixed = dict(out)
    for k in ("study", "primary_findings", "limitations_stated"):
        v = fixed.get(k)
        if isinstance(v, str):
            try:
                fixed[k] = json.loads(v)
            except ValueError:
                pass
    return fixed


def input_hash(title: str, text: str, model: str, prompt_version: str = PROMPT_VERSION) -> str:
    # v2+ also changes the tool schema (quote keys required) and adds quote enforcement; keep those answers apart from v1's
    variant = prompt_version if prompt_version == "v1" else f"{prompt_version}+required-quotes"
    return sha256(title, text, model, variant, SCHEMA_VERSION)


def extract_text(title: str, text: str, sections: list[dict], client: LLMClient,
                 publication_types: list[str] | None = None, prompt_version: str = PROMPT_VERSION) -> ExtractionResult:
    key = input_hash(title, text, client.model, prompt_version)
    user = user_prompt(title, text)
    schema = tool_schema(require_quotes=prompt_version != "v1")
    res = ExtractionResult(status="error")
    last_err = None
    keep = None
    for attempt in range(2):                      # original + one repair
        res.attempts = attempt + 1
        prompt = user if attempt == 0 else (
            f"{user}\n\nYour previous output failed validation:\n{last_err}\nReturn a corrected full output.")
        try:
            resp = client.complete(key if attempt == 0 else f"{key}.repair", get_prompt(prompt_version), prompt, schema)
        except LLMFatalError:
            raise                                  # billing/auth: abort the whole run, don't record per-paper errors
        except Exception as e:
            if keep is not None:                   # the repair call failed: fall back to the first valid answer
                break
            res.error = f"{type(e).__name__}: {e}"
            return res
        res.raw = resp.output
        res.served_model = resp.model or res.served_model
        for k, v in resp.usage.items():
            res.usage[k] = res.usage.get(k, 0) + v
        try:
            ex = PaperExtraction.model_validate(coerce_output(resp.output))
        except ValidationError as e:
            last_err = str(e)[:1500]
            res.status, res.error = "invalid", last_err
            if keep is None:
                continue
            break
        if prompt_version != "v1" and attempt == 0:      # v2+: "no quote, no value", enforced with one repair round
            missing = missing_quotes(ex)
            if missing:
                last_err = ("These fields are reported without a verbatim quote: " + ", ".join(missing)
                            + ". For each, copy a verbatim supporting quote from the abstract, or set status=\"not_reported\".")
                res.status, res.error = "invalid", last_err
                keep = ex                                   # if the repair fails, fall back to this valid-but-unquoted answer
                continue
        res.extraction = verify_extraction(ex, text, sections, publication_types)
        res.status, res.error = "ok", None
        return res
    if keep is not None:             # repair did not produce a better valid answer: keep the first one; its gaps get measured
        res.extraction = verify_extraction(keep, text, sections, publication_types)
        res.status, res.error = "ok", None
    return res


def _load(conn, paper_id: int) -> dict | None:
    return conn.execute(
        "SELECT p.title, p.source_metadata->'pubmed'->'publication_types' AS pts, s.text, s.sections "
        "FROM papers p JOIN source_texts s ON s.paper_id=p.id AND s.source_kind='pubmed_abstract' WHERE p.id=%s",
        (paper_id,)).fetchone()


def _cached(conn, paper_id: int, client: LLMClient, p: dict) -> dict | None:
    return conn.execute(
        "SELECT id, status FROM extraction_runs WHERE paper_id=%s AND model_name=%s AND prompt_version=%s "
        "AND schema_version=%s AND input_hash=%s",
        (paper_id, client.model, PROMPT_VERSION, SCHEMA_VERSION, input_hash(p["title"], p["text"], client.model))).fetchone()


def _store(conn, paper_id: int, client: LLMClient, p: dict, r: ExtractionResult) -> tuple[int, str]:
    out = None
    if r.extraction:
        out = {"extraction": r.extraction.model_dump(mode="json"), "raw": r.raw,
               "verification_summary": verification_summary(r.extraction)}
    elif r.raw:
        out = {"raw": r.raw}
    row = conn.execute(
        "INSERT INTO extraction_runs (paper_id, model_name, prompt_version, schema_version, input_hash, output, "
        "status, usage, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (paper_id, model_name, prompt_version, schema_version, input_hash) DO UPDATE SET "
        "output=EXCLUDED.output, status=EXCLUDED.status, usage=EXCLUDED.usage, error=EXCLUDED.error, created_at=now() "
        "RETURNING id",
        (paper_id, client.model, PROMPT_VERSION, SCHEMA_VERSION, input_hash(p["title"], p["text"], client.model),
         jsonb(out), r.status, jsonb(r.usage), r.error)).fetchone()
    conn.commit()
    return row["id"], r.status


def extract_paper(conn, paper_id: int, client: LLMClient, force: bool = False) -> tuple[int | None, str]:
    """Extract (or return cached) one paper. Returns (extraction_run_id, 'cached'|status)."""
    p = _load(conn, paper_id)
    if not p:
        return None, "no_abstract"
    existing = _cached(conn, paper_id, client, p)
    if existing and existing["status"] == "ok" and not force:
        return existing["id"], "cached"
    return _store(conn, paper_id, client, p, extract_text(p["title"], p["text"], p["sections"], client, p["pts"] or []))


def extract_all(client: LLMClient, force: bool = False, workers: int = 1, missing_only: bool = True,
                only: set[int] | None = None, on_progress=None) -> dict:
    """Extract every paper. LLM calls may run in parallel threads; all database access stays in this thread.
    missing_only: skip papers that already have a successful extraction from *any* model (coverage first; pass False to
    extract again with this model, e.g. to compare models). only: restrict to these paper ids. on_progress(done, total): called as papers finish."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    counts: dict[str, int] = {}
    with connect() as conn:
        todo = []
        for r in conn.execute("SELECT id FROM papers ORDER BY id").fetchall():
            if only is not None and r["id"] not in only:
                continue
            p = _load(conn, r["id"])
            if not p:
                counts["no_abstract"] = counts.get("no_abstract", 0) + 1
                continue
            ex = _cached(conn, r["id"], client, p)
            if missing_only and not ex:
                ex = conn.execute("SELECT id, status FROM extraction_runs WHERE paper_id=%s AND status='ok' LIMIT 1", (r["id"],)).fetchone()
            if ex and ex["status"] == "ok" and not force:
                counts["cached"] = counts.get("cached", 0) + 1
            else:
                todo.append((r["id"], p))
        log.info("%d to extract, %d cached, %d workers", len(todo), counts.get("cached", 0), workers)
        run = lambda p: extract_text(p["title"], p["text"], p["sections"], client, p["pts"] or [])
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futs = {pool.submit(run, p): (pid, p) for pid, p in todo}
            try:
                for fut in as_completed(futs):
                    pid, p = futs[fut]
                    _, st = _store(conn, pid, client, p, fut.result())   # raises LLMFatalError -> abort the rest
                    counts[st] = counts.get(st, 0) + 1
                    log.info("paper %s -> %s (%d/%d)", pid, st, sum(counts.values()) - counts.get("cached", 0), len(todo))
                    if on_progress:
                        on_progress(sum(counts.values()) - counts.get("cached", 0) - counts.get("no_abstract", 0), len(todo))
            except BaseException:
                for f in futs:
                    f.cancel()
                raise
    return counts


if __name__ == "__main__":
    import argparse
    from .llm import LLMFatalError, default_client
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=1, help="parallel LLM calls (free models allow ~20 requests/min)")
    ap.add_argument("--all-models", action="store_true", help="also re-extract papers already extracted by a different model")
    a = ap.parse_args()
    try:
        print(extract_all(default_client(), a.force, a.workers, missing_only=not a.all_models))
    except LLMFatalError as e:
        raise SystemExit(f"aborted: {e}")
