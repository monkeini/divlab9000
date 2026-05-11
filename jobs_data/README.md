# Jobs Data

This folder contains a small SQLite-backed backend for building a job corpus from the Adzuna Jobs API, storing extracted CVs, generating retrieval candidates, and saving deeper LLM match analysis.

## Schema

The database keeps frequently queried fields normalized while preserving each provider response in `jobs.raw_json`.

- `jobs`: one row per Adzuna job id, with title, description, salary, contract, category, company, location, coordinates, redirect URL, and raw JSON.
- `categories`: Adzuna category tags such as `it-jobs` or `engineering-jobs`.
- `companies`: normalized company records by display name.
- `locations`: display name plus the provider's hierarchical `area` array as JSON.
- `scrape_runs`: one row per invocation, including query params, status, count, and mean salary reported by Adzuna.
- `job_scrape_runs`: join table showing which jobs were seen in which run/page/position.
- `cv_documents`: extracted CV text, structured profile JSON, and user-confirmed preferences.
- `cv_match_runs`: one row per matching request, including status, retrieval settings, and index metadata.
- `cv_job_matches`: stored ranked job candidates for a match run, with hybrid retrieval component signals.
- `cv_match_analyses`: stored Stage 2 LLM analysis for a retrieved match.
- `schema_migrations`: applied migration tracking.

## Setup

From this directory:

```bash
uv venv
uv sync
uv run python scripts/migrate.py
```

The scripts look for credentials in environment variables first, then in `.env` / `.enmv` files in this folder or the repository root:

```bash
APP_ID=...
APP_KEY=...
OPENROUTER_KEY=...
```

`OPEN_ROUTER_KEY` is also accepted for the OpenRouter key. CV OCR uses `OPENROUTER_MODEL` when set, otherwise it defaults to `nvidia/nemotron-nano-12b-v2-vl:free`, a free vision-capable OpenRouter model. Stage 2 match analysis uses `OPENROUTER_ANALYSIS_MODEL` when set, otherwise it falls back to `OPENROUTER_MODEL` and then the same default model.

## Scrape Examples

Fetch one category, one page:

```bash
uv run python scripts/scrape_adzuna.py --category it-jobs --pages 1 --results-per-page 20
```

Fetch software engineering roles in London within IT jobs:

```bash
uv run python scripts/scrape_adzuna.py \
  --category it-jobs \
  --what "software engineer" \
  --where London \
  --salary-min 50000 \
  --full-time \
  --permanent \
  --pages 3 \
  --results-per-page 50
```

The default database path is this folder's `jobs.sqlite3` file, i.e. `jobs_data/jobs.sqlite3` from the repository root.

## Matching Indexes

CV matching uses a local hybrid retrieval index:

- BM25 token corpus for keyword matching.
- Dense embedding matrix for semantic matching.
- Metadata with corpus fingerprint, model name, job count, and build timestamp.

The default embedding model is:

```text
BAAI/bge-base-en-v1.5
```

Build or refresh the indexes after scraping new jobs or changing corpus data:

```bash
uv run python scripts/build_match_indexes.py
```

The script writes generated cache files under `jobs_data/indexes/`:

```text
indexes/bm25_tokens.pkl
indexes/dense_embeddings.npy
indexes/metadata.json
```

These files are local artifacts and should not be committed. The script compares the current corpus fingerprint against `indexes/metadata.json` and skips rebuilds when unchanged. Force a rebuild with:

```bash
uv run python scripts/build_match_indexes.py --force
```

The API also calls the same index check before a match run, so `POST /cvs/{document_id}/matches` can build missing indexes synchronously. Running the script up front is still recommended because the first BGE model download and embedding pass can take about a minute for the current corpus.

## API

The FastAPI app exposes the local SQLite job corpus for frontend use, matching experiments, and inspection tools. It also writes uploaded CVs, saved preferences, retrieval runs, stored match candidates, and Stage 2 analysis. Scraping, migrations, and explicit index builds still happen through the scripts above.

Start the app:

```bash
uv run uvicorn jobs_api.main:app --reload --host 127.0.0.1 --port 8000
```

By default the API reads `jobs.sqlite3` in this directory. To point it at another SQLite file:

```bash
JOBS_DB_PATH=/absolute/path/to/jobs.sqlite3 \
  uv run uvicorn jobs_api.main:app --host 127.0.0.1 --port 8000
```

Interactive OpenAPI docs are available at:

```text
http://127.0.0.1:8000/docs
```

### Endpoint Summary

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Lightweight service/database health check. |
| `GET /stats` | Corpus counts and latest scrape-run metadata. |
| `GET /categories` | Available job categories with stored job counts. |
| `GET /jobs` | Paginated job search/list endpoint. |
| `GET /jobs/{adzuna_id}` | Single job detail by Adzuna job id. |
| `POST /cvs/upload` | Upload a CV PDF, OCR it with OpenRouter, and store extracted data. |
| `GET /cvs` | List extracted CV documents. |
| `GET /cvs/{document_id}` | Read one extracted CV document. |
| `PATCH /cvs/{document_id}/preferences` | Save user-confirmed matching preferences for a CV. |
| `POST /cvs/{document_id}/matches` | Run synchronous hybrid retrieval and store ranked job candidates. |
| `GET /cvs/{document_id}/matches` | Return the latest successful stored match run. |
| `GET /cvs/{document_id}/matches/{run_id}` | Return a specific stored match run. |
| `GET /cvs/{document_id}/matches/{run_id}/{match_id}` | Return one match with full job detail and stored analysis if present. |
| `POST /cvs/{document_id}/matches/{run_id}/{match_id}/analysis` | Create or return stored Stage 2 LLM analysis for one match. |
| `GET /scrape-runs` | Recent ingestion runs. |

All endpoints return JSON. CORS is open for `GET`, `POST`, and `PATCH` requests so a local frontend can query the API directly.

### `GET /health`

Returns a minimal status object:

```json
{
  "status": "ok",
  "database_path": "/path/to/jobs.sqlite3",
  "job_count": 22
}
```

Use this for frontend readiness checks.

### `GET /stats`

Returns aggregate corpus metadata:

```json
{
  "job_count": 22,
  "category_count": 1,
  "company_count": 4,
  "location_count": 20,
  "latest_scrape_run": {
    "id": 2,
    "provider": "adzuna",
    "country": "gb",
    "query_params": {
      "category": "it-jobs",
      "content-type": "application/json",
      "results_per_page": 20
    },
    "start_page": 1,
    "end_page": 1,
    "requested_results_per_page": 20,
    "total_count": 51537,
    "mean_salary": 65859.08,
    "status": "success",
    "started_at": "2026-05-09T16:24:25.166Z",
    "finished_at": "2026-05-09T16:24:26.233Z",
    "error_message": null
  }
}
```

### `GET /categories`

Returns categories currently present in the local database:

```json
[
  {
    "tag": "it-jobs",
    "label": "IT Jobs",
    "job_count": 22
  }
]
```

Use `tag` as the `category` filter for `/jobs`.

### `GET /jobs`

Returns paginated job summaries.

Query parameters:

| Parameter | Type | Description |
| --- | --- | --- |
| `q` | string | Searches job title and description with a case-insensitive SQLite `LIKE` match. |
| `category` | string | Exact Adzuna category tag, e.g. `it-jobs`. |
| `location` | string | Matches `locations.display_name` or the stored location area hierarchy. |
| `company` | string | Matches company display name. |
| `salary_min` | number | Keeps jobs where `salary_max >= salary_min`. |
| `salary_max` | number | Keeps jobs where `salary_min <= salary_max`. |
| `contract_type` | string | Exact stored contract type, usually `permanent` or `contract`. |
| `contract_time` | string | Exact stored contract time, usually `full_time` or `part_time`. |
| `limit` | integer | Page size, from `1` to `200`. Default: `25`. |
| `offset` | integer | Number of rows to skip. Default: `0`. |
| `sort` | string | One of `created_desc`, `created_asc`, `salary_max_desc`, `salary_min_desc`, `title_asc`. |

Examples:

```bash
curl 'http://127.0.0.1:8000/jobs?category=it-jobs&limit=25'

curl 'http://127.0.0.1:8000/jobs?q=python&location=London&salary_min=50000'

curl 'http://127.0.0.1:8000/jobs?company=KFC&sort=salary_max_desc&limit=10'
```

Response shape:

```json
{
  "total": 22,
  "limit": 2,
  "offset": 0,
  "results": [
    {
      "adzuna_id": "5723099218",
      "title": "Game Tester Gig - Fast Payout",
      "description": "Become a Professional Game Tester...",
      "redirect_url": "https://www.adzuna.co.uk/jobs/land/ad/5723099218?...",
      "created_at": "2026-05-08T17:32:24Z",
      "scraped_at": "2026-05-09T16:24:26.231Z",
      "updated_at": "2026-05-09T16:24:26.231Z",
      "salary_min": 32368.69,
      "salary_max": 32368.69,
      "salary_is_predicted": true,
      "contract_type": null,
      "contract_time": null,
      "category": {
        "tag": "it-jobs",
        "label": "IT Jobs",
        "job_count": 0
      },
      "company": {
        "id": 18,
        "display_name": "Babki"
      },
      "location": {
        "id": 18,
        "display_name": "Portrush, Coleraine",
        "area": ["UK", "Northern Ireland", "Coleraine", "Portrush"],
        "latitude": 55.1991,
        "longitude": -6.65407
      },
      "latitude": 55.1991,
      "longitude": -6.65407
    }
  ]
}
```

`category.job_count` is populated on `/categories`. Inside job summaries it is set to `0` because the job response is focused on the job record, not category aggregation.

### `GET /jobs/{adzuna_id}`

Returns one job by primary key. `adzuna_id` is the provider job id stored as `jobs.adzuna_id`.

```bash
curl 'http://127.0.0.1:8000/jobs/5723099218'
```

By default this includes the original Adzuna payload in `raw_json`. To suppress it:

```bash
curl 'http://127.0.0.1:8000/jobs/5723099218?include_raw=false'
```

Missing jobs return:

```json
{
  "detail": "Job not found"
}
```

with HTTP status `404`.

### `GET /scrape-runs`

Returns recent ingestion runs, newest first.

Query parameters:

| Parameter | Type | Description |
| --- | --- | --- |
| `limit` | integer | Page size, from `1` to `100`. Default: `20`. |
| `offset` | integer | Number of rows to skip. Default: `0`. |

Example:

```bash
curl 'http://127.0.0.1:8000/scrape-runs?limit=5'
```

Response:

```json
[
  {
    "id": 2,
    "provider": "adzuna",
    "country": "gb",
    "query_params": {
      "category": "it-jobs",
      "content-type": "application/json",
      "results_per_page": 20
    },
    "start_page": 1,
    "end_page": 1,
    "requested_results_per_page": 20,
    "total_count": 51537,
    "mean_salary": 65859.08,
    "status": "success",
    "started_at": "2026-05-09T16:24:25.166Z",
    "finished_at": "2026-05-09T16:24:26.233Z",
    "error_message": null
  }
]
```

### `POST /cvs/upload`

Uploads a CV/resume PDF, renders the PDF pages to images, sends them to OpenRouter for OCR and structure extraction, stores only the extracted data in SQLite, and returns the saved record. The original PDF bytes are not stored.

Request:

```bash
curl -X POST 'http://127.0.0.1:8000/cvs/upload' \
  -F 'file=@/path/to/cv.pdf;type=application/pdf'
```

Environment configuration:

| Variable | Default | Description |
| --- | --- | --- |
| `OPENROUTER_KEY` | none | OpenRouter API key. Required unless `OPEN_ROUTER_KEY` is set. |
| `OPEN_ROUTER_KEY` | none | Alternate accepted spelling for the OpenRouter API key. |
| `OPENROUTER_MODEL` | `nvidia/nemotron-nano-12b-v2-vl:free` | Vision-capable OpenRouter model. |
| `OPENROUTER_ANALYSIS_MODEL` | `OPENROUTER_MODEL` | Optional Stage 2 match-analysis model override. |
| `CV_UPLOAD_MAX_MB` | `10` | Maximum uploaded PDF size. |
| `CV_OCR_MAX_PAGES` | `6` | Maximum number of PDF pages sent to the model. The stored `page_count` still records the original page count. |
| `CV_OCR_RENDER_SCALE` | `2.0` | PDF-to-PNG render scale. Higher values improve OCR detail but increase request size. |

Response shape:

```json
{
  "id": "3b5b2b79-8106-4948-811c-d800f444b10e",
  "original_filename": "cv.pdf",
  "file_sha256": "64-character-sha256",
  "file_size_bytes": 123456,
  "page_count": 2,
  "model": "nvidia/nemotron-nano-12b-v2-vl:free",
  "openrouter_duration_seconds": 24.317,
  "plain_text": "Jane Candidate\nPython engineer...",
  "structured": {
    "name": "Jane Candidate",
    "email": "jane@example.com",
    "phone": null,
    "location": "London",
    "summary": "Python engineer...",
    "skills": ["Python", "FastAPI"],
    "experience": [
      {
        "company": "Example Ltd",
        "title": "Backend Engineer",
        "location": "London",
        "start_date": "2022",
        "end_date": null,
        "current": true,
        "description": "Built APIs...",
        "achievements": ["Improved matching latency"]
      }
    ],
    "education": [],
    "certifications": [],
    "links": ["https://github.com/example"],
    "preferred_roles": ["Backend Engineer"],
    "preferred_locations": ["London"],
    "salary_expectation": null
  },
  "created_at": "2026-05-10T10:00:00.000Z",
  "updated_at": "2026-05-10T10:00:00.000Z"
}
```

Notes:

- The route is synchronous. The HTTP request stays open until OCR, extraction, and database insert are complete.
- `openrouter_duration_seconds` measures only the OpenRouter HTTP call. It does not include PDF rendering, model response parsing, or database insert time. Older rows created before this field existed return `null`.
- The model is instructed not to invent missing CV data. Missing scalar values are saved as `null`; missing lists are saved as `[]`.
- Re-uploading the same PDF creates a new `cv_documents.id`, but the same `file_sha256` can be used to detect duplicates.
- OpenRouter failures return `502`; invalid or unreadable PDFs return `400`; non-PDF uploads return `415`.

### `GET /cvs`

Lists extracted CV records without returning the full `plain_text`.

Query parameters:

| Parameter | Type | Description |
| --- | --- | --- |
| `limit` | integer | Page size, from `1` to `100`. Default: `20`. |
| `offset` | integer | Number of rows to skip. Default: `0`. |

Example:

```bash
curl 'http://127.0.0.1:8000/cvs?limit=10'
```

Response:

```json
[
  {
    "id": "3b5b2b79-8106-4948-811c-d800f444b10e",
    "original_filename": "cv.pdf",
    "file_sha256": "64-character-sha256",
    "file_size_bytes": 123456,
    "page_count": 2,
    "model": "nvidia/nemotron-nano-12b-v2-vl:free",
    "openrouter_duration_seconds": 24.317,
    "candidate_name": "Jane Candidate",
    "candidate_email": "jane@example.com",
    "created_at": "2026-05-10T10:00:00.000Z",
    "updated_at": "2026-05-10T10:00:00.000Z"
  }
]
```

### `GET /cvs/{document_id}`

Returns one extracted CV document, including `plain_text` and the structured CV object.

```bash
curl 'http://127.0.0.1:8000/cvs/3b5b2b79-8106-4948-811c-d800f444b10e'
```

Missing CV documents return:

```json
{
  "detail": "CV document not found"
}
```

with HTTP status `404`.

### `PATCH /cvs/{document_id}/preferences`

Saves user-confirmed matching preferences on the CV document. These fields are separate from model-extracted signals in `structured`.

Request:

```bash
curl -X PATCH 'http://127.0.0.1:8000/cvs/3b5b2b79-8106-4948-811c-d800f444b10e/preferences' \
  -H 'Content-Type: application/json' \
  -d '{
    "preferred_location": "London",
    "salary_min": 90000,
    "salary_max": 140000,
    "working_arrangements": ["hybrid", "remote"],
    "industry_keyword": "fintech platform engineering"
  }'
```

Accepted `working_arrangements` values:

```text
on_site
hybrid
remote
```

The response is the full updated CV document. If both salary fields are present, `salary_min` must be less than or equal to `salary_max`.

### `POST /cvs/{document_id}/matches`

Runs the first checkpoint matching flow synchronously:

1. Verifies the CV exists.
2. Ensures local BM25 and dense embedding indexes exist and match the current job corpus fingerprint.
3. Builds a retrieval query from CV `plain_text`, structured summary, skills, experience, and user-confirmed preferences.
4. Applies salary hard filters where salary bounds are known.
5. Soft-boosts preferred location matches.
6. Stores the top candidates in `cv_match_runs` and `cv_job_matches`.

Request:

```bash
curl -X POST 'http://127.0.0.1:8000/cvs/3b5b2b79-8106-4948-811c-d800f444b10e/matches'
```

Optional query parameters:

| Parameter | Type | Description |
| --- | --- | --- |
| `retrieve_k` | integer | Number of candidates to store, from `1` to `200`. Default: `50`. |
| `rrf_k` | integer | Reciprocal-rank fusion constant, from `1` to `500`. Default: `60`. |

Response:

```json
{
  "run": {
    "id": 1,
    "cv_document_id": "3b5b2b79-8106-4948-811c-d800f444b10e",
    "status": "success",
    "retrieve_count": 50,
    "rrf_k": 60,
    "index_fingerprint": "64-character-sha256",
    "index_model": "BAAI/bge-base-en-v1.5",
    "started_at": "2026-05-10T15:10:00.000Z",
    "finished_at": "2026-05-10T15:10:04.000Z",
    "error_message": null
  },
  "matches": [
    {
      "id": 1,
      "run_id": 1,
      "cv_document_id": "3b5b2b79-8106-4948-811c-d800f444b10e",
      "rank": 1,
      "bm25_rank": 3,
      "dense_rank": 10,
      "rrf_score": 0.0321,
      "bm25_score": 42.5,
      "dense_score": 0.71,
      "preference_filters": {
        "preferred_location": "London",
        "salary_min": 90000,
        "salary_max": 140000,
        "working_arrangements": ["hybrid", "remote"],
        "industry_keyword": "fintech platform engineering",
        "salary_filter_reasons": [],
        "location_boost": 0.015
      },
      "job": {
        "adzuna_id": "5723099218",
        "title": "Platform Engineer",
        "company": {
          "id": 18,
          "display_name": "Example Ltd"
        },
        "location": {
          "id": 18,
          "display_name": "London",
          "area": ["UK", "London"]
        }
      },
      "created_at": "2026-05-10T15:10:04.000Z"
    }
  ]
}
```

Missing CV documents return `404`. Matching failures are recorded on the run as `failed` and returned as `500`.

### `GET /cvs/{document_id}/matches`

Returns the latest successful stored match run for a CV:

```bash
curl 'http://127.0.0.1:8000/cvs/3b5b2b79-8106-4948-811c-d800f444b10e/matches'
```

If no successful match run exists yet, the route returns `404`.

### `GET /cvs/{document_id}/matches/{run_id}`

Returns one stored match run and its ranked candidates:

```bash
curl 'http://127.0.0.1:8000/cvs/3b5b2b79-8106-4948-811c-d800f444b10e/matches/1'
```

### `GET /cvs/{document_id}/matches/{run_id}/{match_id}`

Returns one retrieved match, full job detail, and stored LLM analysis when available:

```bash
curl 'http://127.0.0.1:8000/cvs/3b5b2b79-8106-4948-811c-d800f444b10e/matches/1/25'
```

Before Stage 2 has run for that match, `analysis` is `null`.

### `POST /cvs/{document_id}/matches/{run_id}/{match_id}/analysis`

Runs Stage 2 analysis for one retrieved match if it has not already succeeded. If a successful analysis exists, the endpoint returns it without calling OpenRouter again.

```bash
curl -X POST \
  'http://127.0.0.1:8000/cvs/3b5b2b79-8106-4948-811c-d800f444b10e/matches/1/25/analysis'
```

The analysis model is `OPENROUTER_ANALYSIS_MODEL` when set, otherwise `OPENROUTER_MODEL`, otherwise the same default OpenRouter model used by CV extraction. The response is the match detail payload with a populated `analysis` object:

```json
{
  "analysis": {
    "status": "success",
    "model": "openrouter-model-name",
    "seniority_fit": 8,
    "tech_overlap": 7,
    "domain_fit": 6,
    "responsibilities_fit": 8,
    "location_fit": 9,
    "overall": 8,
    "strengths": ["Specific evidence..."],
    "concerns": ["Specific caveat..."],
    "summary": "Strong platform fit with some domain uncertainty."
  }
}
```

Failures are stored on `cv_match_analyses` with `status = 'failed'` and returned as `500` or `502` depending on whether the failure was local parsing/configuration or an OpenRouter request failure.

### Frontend Usage Notes

For list UIs, call `/jobs` with `limit` and `offset` and use `total` to drive pagination. Fetch `/categories` once for a category filter dropdown. Fetch `/jobs/{adzuna_id}` only when the user opens a detail view, because the detail endpoint can include the larger `raw_json` payload.

For matching workflows, use `POST /cvs/{document_id}/matches` to generate and persist retrieval candidates, then `GET /cvs/{document_id}/matches` to display the latest successful run. The `adzuna_id` should be treated as the stable job key across API responses and database rows.

For CV upload flows, submit the PDF to `/cvs/upload`, keep the returned `id`, and use `/cvs/{document_id}` when the user needs to inspect or edit the extracted profile. Use `plain_text` for semantic matching, `structured` for extracted signals, and `preferences` for user-confirmed matching constraints.

### Error Behavior

```text
400-series validation errors are returned by FastAPI when query parameters fail validation.
404 is returned when requested jobs, CVs, match runs, or individual matches are unknown.
500 indicates local application, parsing, configuration, or database errors.
502 indicates an upstream OpenRouter request failure.
```
