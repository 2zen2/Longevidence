# How the backend works

Longevidence answers a plain-language question with a verdict, a certainty rating, the studies behind it, caveats and links to sources. No language model writes the answer: every sentence points to a stored claim, every claim points to a quote in a stored passage of a paper.

```
PubMed + OpenAlex → papers → documents → passages ←── claim_evidence ──→ claims
                               (abstract, Europe PMC full text)            (verified / needs_review / unsupported)
question → interpret → retrieve → appraise → stance → verdict + certainty → templated statements → audit → cached report
```

## Pipeline

| Step | What happens | Code | Command |
|---|---|---|---|
| Ingest | PubMed search per question in `backend/data/questions.json`, cross-checked against OpenAlex. Identifiers are normalised, so re-running inserts nothing new | `app/ingestion` | `make ingest` |
| Documents | Each abstract (and open-access Europe PMC full text) is stored as a hashed document, split into passages with offsets and a stable `uid` | `app/documents` | `make documents` |
| Claims | Papers are read into claims (design, sample size, population, intervention, a numeric finding...), each with a verbatim quote and a passage uid | `app/extraction`, `app/claims` | `make extract`, `make claims` |
| Index | Passages and papers are embedded with a small local model (the seed data has none: run `make index`); BM25 and metadata indexes are built in memory at start-up | `app/search` | `make index` |
| Add a topic | With a model connected, a topic typed in the web app is turned into a PubMed query and run through the steps above as one background job (see below) | `app/ingestion/topic.py`, `jobs.py` | free-form answer page, `POST /api/ingest` |
| Answer | Rules turn a question into a cached evidence report | `app/synthesis` | `make ask Q="..."` |

## Adding papers on a new topic

Only available when a model is connected (`LLM_PROVIDER`: `anthropic`, `openai`, `openrouter` or `google`, plus `LLM_API_KEY`); `GET /api/ingest/status` says whether it is. The free-form answer page (`/ask`) shows **Research this topic** only then, when the corpus holds little on the question.

1. **Plan:** the model proposes a PubMed query for the topic (e.g. "Avocados and cardiovascular diseases"). If its query is invalid or matches nothing, a plain keyword query is used instead. Nothing is stored yet, and the user can edit the query.
2. **Run:** a background job, one at a time, up to `INGEST_MAX_PAPERS` (default 50) papers, best matches first. Stages: search (PubMed, enriched from OpenAlex) → documents → extract (about one model call per paper, cached by input hash so re-runs are free) → optional full text → claims (verified as above) → embeddings.
3. **Progress:** the job row in `ingest_jobs` records stage, counts, warnings and the papers found; the page polls it. If the model fails fatally (for example out of credit) the papers already stored are kept and the job ends as failed. An embedding failure is only a warning, since keyword search still works.
4. **Restarts:** a job left running when the API stops is marked failed at the next start.

The new papers are searchable straight away; the in-memory index rebuilds when the database changes. In the web app the browser reaches these endpoints through a proxy route, which `INGEST_UI=off` disables (the tunnel demo does this so visitors cannot spend model budget).

## Verification

Every claim is checked against the passage it cites. The quote must be found in the passage (exact, or fuzzy at 90+ similarity), every number must appear in the quote, and a confidence interval must contain its estimate. The result is `verified`, `needs_review` or `unsupported`. Failed claims are kept but never counted. "Verified" means the quote exists and holds the numbers; it does not mean the study is good.

## The answer engine

1. **Interpret:** read the question into an exposure, outcomes and a direction (benefit or harm). Each preset topic in `data/questions.json` lists `aliases` ("bacon", "keto", "ice bath"); an everyday question that names one is routed to that topic, but only if nothing else in it falls outside what the topic measures. Otherwise the rules parse it.
2. **Retrieve:** hybrid search (BM25 + vectors, fused with RRF) for free text, concept queries for preset questions.
3. **Appraise:** weight each study by design, sample size and a bias screen (randomisation, blinding, attrition, etc.).
4. **Stance:** each study supports, is null on, or contradicts the question, from its direction and interval.
5. **Verdict:** weighted shares map to a seven-step label (thresholds 0.65 / 0.40 / 0.20, at least 3 informative studies, otherwise "Insufficient evidence").
6. **Certainty:** GRADE-inspired (starts from design; lowered for bias, inconsistency, imprecision, indirectness), capped at "moderate".
7. **Statements and audit:** conclusions come from templates. An audit re-checks every cited claim and number, and a statement that fails is withheld, not softened.
8. **Caveats:** who the evidence covers, doses, durations, and safety sentences located verbatim in the stored text. Safety is retrieval only; it is never counted toward the verdict.

Reports are cached by input hash in `evidence_reports`.

A model may help only where language is the problem: reading a vague question into an exposure and outcomes, and judging a borderline paper. Ingestion also uses one to read papers into claims and to propose the PubMed query. It can only choose among stored findings. Calls are cached by input hash, capped per day, and optional. Without a key the cached readings replay and everything else falls back to the rules; ingestion is switched off (see [CONFIG.md](CONFIG.md)).

## API

Interactive docs at `/docs` once the API is running.

| Endpoint | Purpose |
|---|---|
| `GET /api/ask?q=...` | Evidence report for a question |
| `GET /api/search?q=...` | Hybrid search over papers, with filters |
| `GET /api/questions` | Preset research questions |
| `GET /api/papers/{id}` | Paper metadata and source links |
| `GET /api/papers/{id}/document` | Stored passages and claims for a paper |
| `GET /api/ingest/status` | Whether ingestion is available (model connected) and any running job |
| `POST /api/ingest/plan` | `{topic}` → proposed PubMed query and match count; stores nothing |
| `POST /api/ingest` | `{topic, query, retmax}` → starts a job (202); 409 if one is running, 422 bad query, 503 no model |
| `GET /api/ingest` | Recent jobs |
| `GET /api/ingest/{id}` | Job progress, counts, warnings and papers |

## Known limits

- The verdict rules suit "does X change Y" trials. Screening and diagnostic questions mostly produce descriptive yields, so the honest answer is often "Insufficient evidence".
- Biomarker and clinical outcomes are treated alike; certainty says how much to lean on a result, not whether the outcome matters for health.
- Studies are weighted and counted, not pooled. Thresholds are hand-set, not calibrated against expert judgement.
- Full text exists only for open-access papers in Europe PMC; the rest are read from abstracts.
- No auth (an optional `INGEST_TOKEN` guards the ingest POSTs, which are also rate-limited); ingestion runs one job at a time in a thread, not a durable queue; the search index is built in memory at start-up.
