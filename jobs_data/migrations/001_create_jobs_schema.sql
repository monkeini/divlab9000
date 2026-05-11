-- 001_create_jobs_schema.sql
--
-- Purpose:
--   Create a normalized SQLite schema for Adzuna job data.
--
-- Design notes:
--   * `jobs.adzuna_id` is the stable provider id and primary key for idempotent upserts.
--   * Company, category, and location data are normalized to keep common filters fast.
--   * `jobs.raw_json` stores the original API result so downstream matching can use fields
--     that are not yet promoted to first-class columns without rescraping.
--   * `scrape_runs` records the exact query params and provider aggregate values for
--     reproducibility and debugging.
--   * `job_scrape_runs` preserves page and result position because provider ranking can be
--     useful signal for later analysis.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS categories (
    tag TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    area_json TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(display_name, area_json)
);

CREATE TABLE IF NOT EXISTS jobs (
    adzuna_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    redirect_url TEXT,
    adref TEXT,
    created_at TEXT,
    scraped_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    salary_min REAL,
    salary_max REAL,
    salary_is_predicted INTEGER NOT NULL DEFAULT 0 CHECK (salary_is_predicted IN (0, 1)),
    contract_type TEXT,
    contract_time TEXT,
    category_tag TEXT REFERENCES categories(tag) ON UPDATE CASCADE,
    company_id INTEGER REFERENCES companies(id) ON UPDATE CASCADE,
    location_id INTEGER REFERENCES locations(id) ON UPDATE CASCADE,
    latitude REAL,
    longitude REAL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL DEFAULT 'adzuna',
    country TEXT NOT NULL,
    query_params_json TEXT NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER,
    requested_results_per_page INTEGER NOT NULL,
    total_count INTEGER,
    mean_salary REAL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS job_scrape_runs (
    job_id TEXT NOT NULL REFERENCES jobs(adzuna_id) ON DELETE CASCADE,
    scrape_run_id INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    result_position INTEGER NOT NULL,
    PRIMARY KEY (job_id, scrape_run_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_category_tag ON jobs(category_tag);
CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_location_id ON jobs(location_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_salary_min ON jobs(salary_min);
CREATE INDEX IF NOT EXISTS idx_jobs_salary_max ON jobs(salary_max);
CREATE INDEX IF NOT EXISTS idx_locations_display_name ON locations(display_name);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_started_at ON scrape_runs(started_at);
