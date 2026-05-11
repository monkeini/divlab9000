-- 005_create_cv_match_analyses.sql
--
-- Purpose:
--   Store Stage 2 LLM analysis for individual retrieved CV/job matches.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cv_match_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES cv_job_matches(id) ON DELETE CASCADE,
    run_id INTEGER NOT NULL REFERENCES cv_match_runs(id) ON DELETE CASCADE,
    cv_document_id TEXT NOT NULL REFERENCES cv_documents(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(adzuna_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    model TEXT,
    seniority_fit INTEGER,
    tech_overlap INTEGER,
    domain_fit INTEGER,
    responsibilities_fit INTEGER,
    location_fit INTEGER,
    overall INTEGER,
    strengths_json TEXT NOT NULL DEFAULT '[]',
    concerns_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT,
    raw_response_json TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    error_message TEXT,
    UNIQUE(match_id)
);

CREATE INDEX IF NOT EXISTS idx_cv_match_analyses_match
    ON cv_match_analyses(match_id);
CREATE INDEX IF NOT EXISTS idx_cv_match_analyses_run
    ON cv_match_analyses(run_id);
CREATE INDEX IF NOT EXISTS idx_cv_match_analyses_cv
    ON cv_match_analyses(cv_document_id);
