"""Topic ingestion: query planning, the job pipeline (fake PubMed/OpenAlex/model, throwaway Postgres) and the API guards."""
import pytest

from app.extraction.llm import LLMFatalError, LLMResponse
from app.ingestion import jobs, topic
from app.ingestion.pubmed import parse_efetch

NR = {"status": "not_reported"}
FOUND = {"study": {"design": NR, "population": NR, "intervention": NR, "comparator": NR, "follow_up": NR,
                   "sample_size": {"status": "reported", "value": 200, "quote": "We randomized 200 patients"}},
         "primary_findings": []}
EMPTY = {"study": {k: NR for k in ("design", "population", "intervention", "comparator", "follow_up", "sample_size")}, "primary_findings": []}


class FakeLLM:
    provider, model = "test", "fake-model"

    def __init__(self, query="(avocado*[Title/Abstract]) AND hasabstract[text]", fatal=False):
        self.query, self.fatal, self.calls = query, fatal, 0

    def complete(self, key, system, user, schema):
        self.calls += 1
        if self.fatal:
            raise LLMFatalError("HTTP 402: out of credit")
        if "query" in schema.get("properties", {}):
            return LLMResponse({"query": self.query, "rationale": "avocado AND heart"}, {}, self.model)
        return LLMResponse(FOUND if "We randomized 200 patients" in user else EMPTY, {"input_tokens": 1, "output_tokens": 1}, self.model)


class FakePubMed:
    def __init__(self, xml, pmids=("111", "222", "333"), counts=None, fail=False):
        self.xml, self.pmids, self.counts, self.fail, self.sorts = xml, list(pmids), counts, fail, []

    def search(self, q, retmax=30, sort="pub_date"):
        if self.fail:
            raise RuntimeError("NCBI down")
        self.sorts.append(sort)
        n = self.counts.pop(0) if self.counts else len(self.pmids)
        return self.pmids[:retmax], n

    def fetch(self, pmids):
        return [r for r in parse_efetch(self.xml) if r.pmid in pmids]


class NoOpenAlex:
    def get_by(self, pmid, doi):
        return None


@pytest.fixture
def embedded(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "build_embeddings", lambda ids=None: calls.append(ids) or {"paper": {"embedded": len(ids), "total": len(ids)}})
    return calls


def _run(xml, llm=None, **kw):
    jid = jobs.create_job("Avocados and heart disease", "avocado*[Title/Abstract]", 30)
    pm = FakePubMed(xml, **kw)
    jobs.run_job(jid, client=llm or FakeLLM(), pubmed=pm, openalex=NoOpenAlex())
    return jid, pm


# ---- query planning (no database)
def test_fallback_query_and_validation():
    q = topic.fallback_query("Avocados and cardiovascular diseases!")
    assert q == "(avocados[Title/Abstract] AND cardiovascular[Title/Abstract] AND diseases[Title/Abstract]) AND hasabstract[text]"
    assert topic.valid_query(q)
    assert not topic.valid_query("(unbalanced") and not topic.valid_query('"open quote') and not topic.valid_query("")
    assert not topic.valid_query("x" * 900)
    with pytest.raises(ValueError):
        topic.fallback_query("the of and")


def test_plan_uses_the_model_query_when_it_matches_something():
    pm = FakePubMed(b"", counts=[42])
    r = topic.plan_query("Avocados and heart", FakeLLM(), pm)
    assert r["source"] == "model" and r["count"] == 42 and r["query"].startswith("(avocado*")


def test_plan_falls_back_when_the_model_query_is_invalid_or_empty():
    r = topic.plan_query("Avocados and heart", FakeLLM(query="((broken"), FakePubMed(b"", counts=[7]))
    assert r["source"] == "keywords" and r["count"] == 7
    r = topic.plan_query("Avocados and heart", FakeLLM(), FakePubMed(b"", counts=[0, 5]))   # model query matches nothing
    assert r["source"] == "keywords" and r["count"] == 5


def test_plan_does_not_hide_a_billing_failure():
    with pytest.raises(LLMFatalError):
        topic.plan_query("Avocados and heart", FakeLLM(fatal=True), FakePubMed(b""))


def test_llm_status(monkeypatch):
    from app.config import settings
    from app.extraction.llm import llm_status
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "llm_model", "m")
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert llm_status()["ready"] is False and "LLM_API_KEY" in llm_status()["reason"]
    monkeypatch.setattr(settings, "llm_api_key", "sk-secret")
    st = llm_status()
    assert st["ready"] and "sk-secret" not in str(st)
    monkeypatch.setattr(settings, "llm_provider", "google")
    assert llm_status()["ready"] is True
    monkeypatch.setattr(settings, "llm_provider", "cloudflare")       # no longer supported
    assert llm_status()["ready"] is False and "unknown" in llm_status()["reason"]
    monkeypatch.setattr(settings, "llm_provider", "nope")
    assert llm_status()["ready"] is False


# ---- the job pipeline
@pytest.mark.db
def test_job_runs_every_stage(test_db, efetch_xml, embedded):
    from app.db import connect
    jid, pm = _run(efetch_xml)
    j = jobs.job_view(jid)
    assert j["status"] == "done" and j["stage"] == "done" and j["error"] is None and j["finished_at"]
    assert pm.sorts == ["relevance"]                       # topic ingestion asks for best matches, not newest
    assert j["n_papers"] == 3 and j["counts"]["inserted"] == 3 and j["counts"]["no_abstract"] == 1
    assert j["counts"]["extraction"]["ok"] == 2 and j["counts"]["claims"] >= 1
    assert sum(p["extracted"] for p in j["papers"]) == 2 and sum(p["claims"] for p in j["papers"]) == j["counts"]["claims"]
    assert embedded and len(embedded[0]) == 3
    with connect() as c:
        assert c.execute("SELECT count(*) n FROM documents WHERE kind='pubmed_abstract'").fetchone()["n"] == 2
        assert c.execute("SELECT count(*) n FROM question_papers").fetchone()["n"] == 3


@pytest.mark.db
def test_rerun_reuses_stored_work(test_db, efetch_xml, embedded):
    llm = FakeLLM()
    _run(efetch_xml, llm)
    first = llm.calls
    jid, _ = _run(efetch_xml, llm)
    assert jobs.job_view(jid)["status"] == "done" and llm.calls == first      # extraction served from the database, not the model


@pytest.mark.db
def test_only_one_job_at_a_time(test_db):
    jobs.create_job("a topic", "a[Title/Abstract]", 10)
    with pytest.raises(jobs.JobBusy):
        jobs.create_job("another", "b[Title/Abstract]", 10)


@pytest.mark.db
def test_retmax_is_capped(test_db, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ingest_max_papers", 5)
    jid = jobs.create_job("a topic", "a[Title/Abstract]", 500)
    assert jobs.job_view(jid)["params"]["retmax"] == 5


@pytest.mark.db
def test_model_billing_failure_keeps_papers_and_reports_it(test_db, efetch_xml, embedded):
    jid, _ = _run(efetch_xml, FakeLLM(fatal=True))
    j = jobs.job_view(jid)
    assert j["status"] == "failed" and "402" in j["error"] and j["finished_at"]
    assert j["n_papers"] == 3 and j["counts"]["claims"] == 0          # papers are stored, later stages still ran on what exists


@pytest.mark.db
def test_pubmed_failure_fails_the_job(test_db, efetch_xml, embedded):
    jid, _ = _run(efetch_xml, fail=True)
    j = jobs.job_view(jid)
    assert j["status"] == "failed" and "NCBI down" in j["error"] and not embedded


@pytest.mark.db
def test_embedding_failure_is_a_warning(test_db, efetch_xml, monkeypatch):
    def boom(ids=None):
        raise RuntimeError("model download failed")
    monkeypatch.setattr(jobs, "build_embeddings", boom)
    jid, _ = _run(efetch_xml)
    j = jobs.job_view(jid)
    assert j["status"] == "done" and any("semantic index" in w for w in j["warnings"])


@pytest.mark.db
def test_restart_marks_orphaned_jobs_failed(test_db):
    jid = jobs.create_job("a topic", "a[Title/Abstract]", 10)
    assert jobs.recover_orphans() == 1
    j = jobs.job_view(jid)
    assert j["status"] == "failed" and "restart" in j["error"]
    jobs.create_job("another", "b[Title/Abstract]", 10)           # no longer blocked


# ---- API guards
@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import ingest
    from app.main import app
    monkeypatch.setattr(ingest.jobs, "start_job", lambda jid: None)      # do not spawn the background thread
    return TestClient(app), ingest, monkeypatch


def _ready(ingest, monkeypatch, ready=True):
    st = {"ready": ready, "provider": "test", "model": "m", "reason": None if ready else "no LLM_API_KEY configured"}
    monkeypatch.setattr(ingest, "llm_status", lambda: st)


@pytest.mark.db
def test_api_is_closed_without_a_model(test_db, client):
    c, ingest, mp = client
    _ready(ingest, mp, ready=False)
    s = c.get("/api/ingest/status").json()
    assert s["enabled"] is False and "LLM_API_KEY" in s["reason"]
    assert c.post("/api/ingest/plan", json={"topic": "avocados and heart"}).status_code == 503
    assert c.post("/api/ingest", json={"topic": "avocados", "query": "avocado[Title/Abstract]"}).status_code == 503


@pytest.mark.db
def test_api_start_status_and_busy(test_db, client):
    c, ingest, mp = client
    _ready(ingest, mp)
    assert c.get("/api/ingest/status").json()["enabled"] is True
    mp.setattr(ingest, "ingest_client", lambda: FakeLLM())
    mp.setattr(ingest, "plan_query", lambda t, cl: {"topic": t, "query": "x[Title/Abstract]", "rationale": None, "source": "model", "count": 3})
    assert c.post("/api/ingest/plan", json={"topic": "avocados and heart"}).json()["count"] == 3
    body = {"topic": "avocados and heart", "query": "avocado*[Title/Abstract]", "retmax": 20}
    r = c.post("/api/ingest", json=body)
    assert r.status_code == 202
    jid = r.json()["job_id"]
    assert c.get(f"/api/ingest/{jid}").json()["status"] == "queued"
    assert c.get("/api/ingest/status").json()["active_job"] == jid
    assert c.post("/api/ingest", json=body).status_code == 409
    assert c.get("/api/ingest/99999").status_code == 404
    assert c.get("/api/ingest").json()[0]["id"] == jid


@pytest.mark.db
def test_api_rejects_malformed_input(test_db, client):
    c, ingest, mp = client
    _ready(ingest, mp)
    assert c.post("/api/ingest", json={"topic": "avocados", "query": "((oops"}).status_code == 422
    assert c.post("/api/ingest", json={"topic": "x", "query": "avocado[Title/Abstract]"}).status_code == 422
    assert c.post("/api/ingest", json={"topic": "avocados", "query": "avocado[Title/Abstract]", "retmax": 0}).status_code == 422
