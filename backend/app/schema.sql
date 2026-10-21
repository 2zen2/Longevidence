-- Longevidence schema. Idempotent: safe to run repeatedly (make migrate).

CREATE TABLE IF NOT EXISTS papers (
    id               BIGSERIAL PRIMARY KEY,
    title            TEXT NOT NULL,
    abstract         TEXT,
    publication_date DATE,
    journal          TEXT,
    study_type       TEXT,                 -- PubMed's own publication-type label(s), not LLM output
    source_metadata  JSONB,
    content_hash     TEXT,                 -- hash of normalized content; unchanged hash => no update
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_identifiers (
    id               BIGSERIAL PRIMARY KEY,
    paper_id         BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    source           TEXT NOT NULL,        -- pubmed | openalex
    identifier_type  TEXT NOT NULL,        -- pmid | doi | pmc | openalex_id
    identifier_value TEXT NOT NULL,        -- normalized form
    UNIQUE (source, identifier_type, identifier_value)
);
CREATE INDEX IF NOT EXISTS paper_identifiers_paper_idx ON paper_identifiers(paper_id);
CREATE INDEX IF NOT EXISTS paper_identifiers_lookup_idx ON paper_identifiers(identifier_type, identifier_value);

-- The exact text evidence quotes point into; source_kind makes evidence provenance explicit.
CREATE TABLE IF NOT EXISTS source_texts (
    id          BIGSERIAL PRIMARY KEY,
    paper_id    BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,             -- pubmed_abstract | pmc_fulltext
    text        TEXT NOT NULL,
    sections    JSONB NOT NULL DEFAULT '[]',
    text_hash   TEXT NOT NULL,
    UNIQUE (paper_id, source_kind)
);

CREATE TABLE IF NOT EXISTS research_questions (
    id         BIGSERIAL PRIMARY KEY,
    question   TEXT NOT NULL,
    query      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (query)
);

CREATE TABLE IF NOT EXISTS question_papers (
    question_id  BIGINT NOT NULL REFERENCES research_questions(id) ON DELETE CASCADE,
    paper_id     BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    rank         INT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (question_id, paper_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    query       TEXT,
    question_id BIGINT REFERENCES research_questions(id) ON DELETE SET NULL,
    status      TEXT NOT NULL DEFAULT 'running',   -- running | success | partial | failed
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    counts      JSONB NOT NULL DEFAULT '{}',
    errors      JSONB NOT NULL DEFAULT '[]',
    params      JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS extraction_runs (
    id             BIGSERIAL PRIMARY KEY,
    paper_id       BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    model_name     TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    input_hash     TEXT NOT NULL,
    output         JSONB,
    status         TEXT NOT NULL,          -- ok | invalid | error
    usage          JSONB,
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (paper_id, model_name, prompt_version, schema_version, input_hash)
);

-- Full-text search over the corpus (title + abstract). Idempotent.
CREATE INDEX IF NOT EXISTS papers_fts_idx ON papers
    USING GIN (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, '')));

-- ============================================================================================================
-- System B: evidence as first-class records.
-- documents  = one stored, hashed version of a paper's text (abstract, PMC JATS full text, later PDF).
-- passages   = addressable spans of a document, with a content-derived stable id (uid) and offsets into documents.text.
-- claims     = what a paper asserts (design, population, a finding ...), extracted by a model or rule.
-- claim_evidence = claim <-> passage links with role and verification. Many-to-many: one passage can bear on several
--                  claims, and one claim can be backed by an abstract sentence AND a results paragraph AND a table row.
-- ============================================================================================================
CREATE TABLE IF NOT EXISTS documents (
    id             BIGSERIAL PRIMARY KEY,
    paper_id       BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,              -- pubmed_abstract | pmc_jats | pdf
    source_url     TEXT,
    license        TEXT,                       -- SPDX-like or URL as stated by the publisher; NULL = not stated
    raw_path       TEXT,                       -- original file kept on disk (relative to data_dir); NULL for abstracts
    raw_sha256     TEXT,
    text           TEXT NOT NULL,              -- normalized text; passage offsets point into this
    text_hash      TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    printed_pages  TEXT,                       -- journal page range as printed, e.g. '2933-2940' (not a PDF page index)
    meta           JSONB NOT NULL DEFAULT '{}',
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (paper_id, kind)
);

CREATE TABLE IF NOT EXISTS passages (
    id            BIGSERIAL PRIMARY KEY,
    uid           TEXT NOT NULL UNIQUE,        -- sha1(document text_hash | start | end)[:12]: stable for identical text
    document_id   BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    paper_id      BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    ordinal       INT NOT NULL,
    section       TEXT NOT NULL,               -- canonical: background|methods|results|discussion|conclusions|funding_coi|other
    section_title TEXT,                        -- as printed, with path: 'Results > Safety outcomes'
    kind          TEXT NOT NULL,               -- abstract_section | paragraph | table | figure_caption | note
    label         TEXT,                        -- 'Table 2', 'Figure 1'
    page_number   INT,                         -- PDF page index (1-based) when known; NULL for JATS-derived passages
    printed_page  TEXT,                        -- page label as printed, when known
    text          TEXT NOT NULL,
    start_offset  INT NOT NULL,
    end_offset    INT NOT NULL,
    table_json    JSONB,                       -- header + rows for kind='table'
    text_hash     TEXT NOT NULL,
    UNIQUE (document_id, ordinal)
);
CREATE INDEX IF NOT EXISTS passages_paper_idx ON passages(paper_id);
CREATE INDEX IF NOT EXISTS passages_fts_idx ON passages USING GIN (to_tsvector('english', text));

CREATE TABLE IF NOT EXISTS claims (
    id                BIGSERIAL PRIMARY KEY,
    paper_id          BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    extraction_run_id BIGINT REFERENCES extraction_runs(id) ON DELETE CASCADE,
    claim_key         TEXT NOT NULL,           -- 'study.design' | 'finding.0' | 'limitation.1'
    claim_type        TEXT NOT NULL,           -- design|sample_size|population|intervention|comparator|follow_up|finding|limitation
    text              TEXT NOT NULL,           -- human-readable statement
    structured        JSONB NOT NULL DEFAULT '{}',
    extraction_status TEXT NOT NULL,           -- verified | needs_review | unsupported
    status_reasons    TEXT[] NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (extraction_run_id, claim_key)
);
CREATE INDEX IF NOT EXISTS claims_paper_idx ON claims(paper_id);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id            BIGSERIAL PRIMARY KEY,
    claim_id      BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    passage_id    BIGINT NOT NULL REFERENCES passages(id) ON DELETE CASCADE,
    evidence_role TEXT NOT NULL,               -- supports | contradicts | contextualizes
    origin        TEXT NOT NULL,               -- extractor_quote | numeric_match
    quote_start   INT NOT NULL,                -- offsets inside passages.text
    quote_end     INT NOT NULL,
    verification  TEXT NOT NULL,               -- exact | fuzzy | numeric
    extraction_status TEXT NOT NULL,           -- verified | needs_review
    UNIQUE (claim_id, passage_id, quote_start, origin)
);
CREATE INDEX IF NOT EXISTS claim_evidence_claim_idx ON claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS claim_evidence_passage_idx ON claim_evidence(passage_id);

CREATE TABLE IF NOT EXISTS fulltext_attempts (
    id           BIGSERIAL PRIMARY KEY,
    paper_id     BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    source       TEXT NOT NULL,                -- europepmc
    status       TEXT NOT NULL,                -- ok | not_available | no_license | error | no_pmcid
    detail       TEXT,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (paper_id, source)
);

-- ============================================================================================================
-- System C: stored evidence reports (a question -> evidence-linked answer), kept so an answer can be re-audited.
-- ============================================================================================================
CREATE TABLE IF NOT EXISTS evidence_reports (
    id             BIGSERIAL PRIMARY KEY,
    question       TEXT NOT NULL,
    interpretation JSONB NOT NULL,
    report         JSONB NOT NULL,
    input_hash     TEXT NOT NULL,              -- hash of question + the claims/passages it was computed from
    engine_version TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (input_hash, engine_version)
);

-- ============================================================================================================
-- Full-text extraction: the model reads selected passages (each labelled with its passage uid) and must cite a uid + verbatim
-- quote. Kept apart from extraction_runs (abstract extraction, scored by the gold-set evaluation).
-- ============================================================================================================
CREATE TABLE IF NOT EXISTS fulltext_runs (
    id             BIGSERIAL PRIMARY KEY,
    paper_id       BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    document_id    BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    model_name     TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    input_hash     TEXT NOT NULL,
    output         JSONB,
    status         TEXT NOT NULL,              -- ok | invalid | error
    usage          JSONB,
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (paper_id, model_name, prompt_version, schema_version, input_hash)
);
ALTER TABLE claims ADD COLUMN IF NOT EXISTS ft_run_id BIGINT REFERENCES fulltext_runs(id) ON DELETE CASCADE;
CREATE UNIQUE INDEX IF NOT EXISTS claims_ft_key ON claims(ft_run_id, claim_key) WHERE ft_run_id IS NOT NULL;

-- ============================================================================================================
-- Search indexes. Keyword (BM25) and metadata indexes are built in memory from papers/passages/claims at first use (a few hundred
-- papers: milliseconds). Only the expensive part, embeddings, is stored here, keyed by text hash so re-indexing is incremental.
-- ============================================================================================================
CREATE TABLE IF NOT EXISTS embeddings (
    kind      TEXT NOT NULL,                 -- paper | passage
    ref_id    BIGINT NOT NULL,               -- papers.id or passages.id
    model     TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    vec       BYTEA NOT NULL,                -- float32, L2-normalised
    PRIMARY KEY (kind, ref_id, model)
);

-- ============================================================================================================
-- Model assist at answer time (claim reading, borderline-finding judging). Every call is cached by input hash and counted against a daily cap.
-- The model only proposes; stored claims, quotes and numbers are still checked by code.
-- ============================================================================================================
CREATE TABLE IF NOT EXISTS llm_cache (
    key        TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,                  -- read_claim | judge_paper
    model      TEXT NOT NULL,
    request    JSONB NOT NULL,
    output     JSONB NOT NULL,
    usage      JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================================================
-- Topic ingestion jobs (POST /api/ingest): one row per run of search -> persist -> extract -> claims -> embed.
-- ============================================================================================================
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id          BIGSERIAL PRIMARY KEY,
    topic       TEXT NOT NULL,
    query       TEXT NOT NULL,
    params      JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'queued',    -- queued | running | done | failed
    stage       TEXT NOT NULL DEFAULT 'queued',    -- queued | search | documents | extract | fulltext | claims | embed | done
    done        INT NOT NULL DEFAULT 0,            -- progress inside the current stage
    total       INT NOT NULL DEFAULT 0,
    counts      JSONB NOT NULL DEFAULT '{}',
    warnings    JSONB NOT NULL DEFAULT '[]',
    error       TEXT,
    question_id BIGINT REFERENCES research_questions(id) ON DELETE SET NULL,
    paper_ids   BIGINT[] NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
