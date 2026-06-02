-- Curator Stage-2 Spanner schema (D2 baseline).
--
-- Conservative GoogleSQL DDL — tables only, no property graph or vector
-- indexes yet. Phase 2 (D4) extends this with PROPERTY GRAPH + vector
-- columns for retrieval. Phase 2.5 (D5) adds the discovered_items hooks.
--
-- All DDL statements are idempotent in spirit; gcloud's
-- `spanner databases ddl update --ddl-file` will fail if a statement
-- conflicts with existing schema, so re-running the script after the
-- first apply requires either schema bump or `spanner_down.sh` first.
--
-- Apply via:
--   bash scripts/spanner_up.sh                       # picks up this file
-- or:
--   gcloud spanner databases ddl update curator \
--     --instance=curator-graph --project=curator-research \
--     --ddl-file=app/ingest/spanner_schema.sql

-- ---------------------------------------------------------------------------
-- Documents — top-level ingested regulatory PDFs.
-- ---------------------------------------------------------------------------
CREATE TABLE documents (
  doc_id           STRING(64)  NOT NULL,
  namespace        STRING(64)  NOT NULL,        -- demo run / tenant
  source_url       STRING(MAX),
  source_pdf_path  STRING(MAX),
  title            STRING(MAX),
  doc_kind         STRING(32),                  -- amendment / master_direction / policy
  published_at     DATE,
  ingested_at      TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp=true),
  raw_text         STRING(MAX),
) PRIMARY KEY (doc_id);

CREATE INDEX documents_by_namespace ON documents (namespace, doc_kind);

-- ---------------------------------------------------------------------------
-- Clauses — extracted from documents during ingestion.
-- ---------------------------------------------------------------------------
CREATE TABLE clauses (
  doc_id        STRING(64)  NOT NULL,
  clause_id     STRING(128) NOT NULL,
  heading       STRING(MAX),
  old_text      STRING(MAX),
  new_text      STRING(MAX),
  change_type   STRING(16),                     -- insert / modify / delete / renumber
  ord           INT64,
) PRIMARY KEY (doc_id, clause_id),
  INTERLEAVE IN PARENT documents ON DELETE CASCADE;

-- ---------------------------------------------------------------------------
-- Policy sections — bank-side policy text (mock for D2, real for D4+).
-- ---------------------------------------------------------------------------
CREATE TABLE policy_sections (
  policy_id          STRING(64)  NOT NULL,
  policy_section_id  STRING(128) NOT NULL,
  bank_id            STRING(64)  NOT NULL,
  title              STRING(MAX),
  heading            STRING(MAX),
  section_text       STRING(MAX),
  owner_department   STRING(64),
) PRIMARY KEY (bank_id, policy_id, policy_section_id);

-- ---------------------------------------------------------------------------
-- Obligations — atomic regulatory obligations (post-reconciliation).
-- ---------------------------------------------------------------------------
CREATE TABLE obligations (
  obligation_id      STRING(128) NOT NULL,
  source_clause_id   STRING(128) NOT NULL,
  doc_id             STRING(64)  NOT NULL,
  deontic_type       STRING(16),               -- must / must_not / may / should
  subject            STRING(MAX),
  action             STRING(MAX),
  condition          STRING(MAX),
  temporal_scope     STRING(MAX),
  owner_hint         STRING(MAX),
  confidence         FLOAT64,
  missing_evidence   ARRAY<STRING(MAX)>,
  agent_run_id       STRING(64),                -- which agent_run produced this
) PRIMARY KEY (obligation_id);

CREATE INDEX obligations_by_clause ON obligations (doc_id, source_clause_id);

-- ---------------------------------------------------------------------------
-- agent_runs — observability log for every real-LLM agent invocation.
-- Drives the GEPA / SimplePromptOptimizer feedback loop on D7.
-- ---------------------------------------------------------------------------
CREATE TABLE agent_runs (
  run_id                STRING(64)  NOT NULL,
  ts                    TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp=true),
  agent_name            STRING(64)  NOT NULL,
  lens                  STRING(64),                 -- one of the 4 panel lenses, or NULL
  prompt_hash           STRING(64),                 -- sha256 of (instruction + user_text)
  input_json            STRING(MAX),
  output_json           STRING(MAX),
  confidence            FLOAT64,
  latency_ms            INT64,
  cost_usd_estimated    FLOAT64,
  eval_score            FLOAT64,                    -- backfilled when an eval scores this run
  parent_run_id         STRING(64),                 -- for sub-runs (reflector → re-queried panel)
  pipeline_run_id       STRING(64),                 -- groups all runs from one chain invocation
  error                 STRING(MAX),
) PRIMARY KEY (run_id);

CREATE INDEX agent_runs_by_agent_ts ON agent_runs (agent_name, ts DESC);
CREATE INDEX agent_runs_by_pipeline ON agent_runs (pipeline_run_id, ts);

-- ---------------------------------------------------------------------------
-- discovered_items — RBI RSS polling dedupe + linkage to the run that
-- processed each item. Populated by the D5 discovery agent.
-- ---------------------------------------------------------------------------
CREATE TABLE discovered_items (
  item_hash       STRING(64)  NOT NULL,
  source          STRING(32)  NOT NULL,             -- "rbi_rss" for now
  url             STRING(MAX),
  title           STRING(MAX),
  published_at    TIMESTAMP,
  first_seen      TIMESTAMP   NOT NULL OPTIONS (allow_commit_timestamp=true),
  processed_at    TIMESTAMP,
  pipeline_run_id STRING(64),                       -- → agent_runs.pipeline_run_id
  status          STRING(32),                       -- "new" / "processing" / "done" / "error"
) PRIMARY KEY (item_hash);

CREATE INDEX discovered_items_by_first_seen ON discovered_items (first_seen DESC);
CREATE INDEX discovered_items_by_status ON discovered_items (status, first_seen DESC);
