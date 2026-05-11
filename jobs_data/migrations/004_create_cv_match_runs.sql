-- 004_create_cv_match_runs.sql
--
-- Purpose:
--   Store retrieval-only candidate job matches for each CV matching request.
--
-- Design notes:
--   * `cv_match_runs` records one synchronous retrieval run.
--   * `cv_job_matches` stores the ranked candidates and component retrieval signals.
--   * LLM fit scores and explanations are intentionally deferred to a later checkpoint.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cv_match_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cv_document_id TEXT NOT NULL REFERENCES cv_documents(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    retrieve_count INTEGER NOT NULL,
    rrf_k INTEGER NOT NULL,
    index_fingerprint TEXT,
    index_model TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS cv_job_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES cv_match_runs(id) ON DELETE CASCADE,
    cv_document_id TEXT NOT NULL REFERENCES cv_documents(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(adzuna_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    bm25_rank INTEGER,
    dense_rank INTEGER,
    rrf_score REAL NOT NULL,
    bm25_score REAL NOT NULL,
    dense_score REAL NOT NULL,
    preference_filters_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(run_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_cv_match_runs_cv_status
    ON cv_match_runs(cv_document_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cv_job_matches_run_rank
    ON cv_job_matches(run_id, rank);
CREATE INDEX IF NOT EXISTS idx_cv_job_matches_cv
    ON cv_job_matches(cv_document_id);
