-- 003_add_cv_matching_preferences.sql
--
-- Purpose:
--   Store candidate-confirmed matching preferences on each extracted CV document.
--
-- Design notes:
--   * Preferences live on `cv_documents` for now because the demo treats each uploaded CV
--     as one candidate profile.
--   * `working_arrangements_json` stores a JSON list so candidates can select one or more
--     of: `on_site`, `hybrid`, `remote`.
--   * Extracted model signals remain in `structured_json`; these columns are user-confirmed
--     matching inputs.

ALTER TABLE cv_documents ADD COLUMN preferred_location TEXT;
ALTER TABLE cv_documents ADD COLUMN salary_min INTEGER;
ALTER TABLE cv_documents ADD COLUMN salary_max INTEGER;
ALTER TABLE cv_documents ADD COLUMN working_arrangements_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE cv_documents ADD COLUMN industry_keyword TEXT;
