# DivLab9000 Frontend

Local demo frontend for `DivLab9000 - Division of Labour as-a-service`.

## Setup

```bash
npm install
```

## Run

In one terminal, start the FastAPI backend:

```bash
cd ../jobs_data
uv run uvicorn jobs_api.main:app --host 127.0.0.1 --port 8000
```

In another terminal, build the local BM25 and embedding indexes after scraping or changing job data:

```bash
cd ../jobs_data
uv run python scripts/build_match_indexes.py
```

The API can build missing indexes during Begin Match, but running the script first avoids making the first UI match request wait for the BGE embedding pass.

Then start the frontend from the `frontend` directory:

```bash
npm run dev
```

Open:

```text
http://127.0.0.1:5173/
```

## Configuration

The frontend calls the backend directly. Override the API base URL with:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

## Checks

```bash
npm run lint
npm run build
```
