-- 002_create_cv_documents.sql
--
-- Purpose:
--   Store extracted CV data from uploaded PDFs.
--
-- Design notes:
--   * The original PDF bytes are intentionally not stored.
--   * `plain_text` contains the OCR/transcribed text for search and inspection.
--   * `structured_json` contains normalized CV fields extracted by the vision model.
--   * `file_sha256` lets us identify repeat uploads without forcing de-duplication.
--   * `provider_response_json` stores lightweight model/usage metadata and the raw
--     assistant message for debugging extraction quality.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cv_documents (
    id TEXT PRIMARY KEY,
    original_filename TEXT,
    file_sha256 TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    model TEXT NOT NULL,
    plain_text TEXT NOT NULL,
    structured_json TEXT NOT NULL,
    provider_response_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_cv_documents_file_sha256 ON cv_documents(file_sha256);
CREATE INDEX IF NOT EXISTS idx_cv_documents_created_at ON cv_documents(created_at);
