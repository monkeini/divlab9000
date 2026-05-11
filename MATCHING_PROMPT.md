# Build a CV-to-Jobs Matcher: Hybrid Retrieval + LLM Scoring

## Goal

Build the matching layer that takes a CV (data already extracted from PDF) and ranks a corpus of ~5000 job descriptions, producing a top-N list with structured scores and natural-language explanations of why each is a good fit. 

This flow should be instigated on the individual CV page, and lead to a ${HOST}/cvs/${CV_ID}/matches endpoint.

We need to consider the ahead-of-time work to do on the CV corpus, the work that's done on CV upload, the retreival matching, and then the LLM stage. 

## Inputs (already exist)

- A corpus of ~5000 jobs, as structured data. This is already in the db.
- A CV, already uploaded and parsed. 

## Architecture

Two-stage pipeline:

1. **Retrieval (hybrid BM25 + dense embeddings)** narrows 5000 → top 50.
2. **LLM scoring** evaluates each of the 50 against the CV, produces structured scores and explanation.

Final output: ranked list of top N (default 20), each with scores and reasoning, written to db as a cv_job_match table entry, linking to both cv and job. 

## Stage 1: Hybrid Retrieval

### Indexing (one-time, cached to disk)

- Build a BM25 index over the corpus using `rank_bm25` (the `BM25Okapi` variant). Tokenise with simple lowercasing + punctuation stripping; do not stem.
- Embed each job using a local sentence-transformer. Default to `BAAI/bge-large-en-v1.5` via `sentence-transformers`. Store as a single `numpy` float32 array, shape `(N, dim)`, alongside a parallel list of job IDs.
- Cache both indexes to disk or db - recommend approach. Detect corpus changes via a hash of the input file(s) and rebuild only on mismatch (optional).

### Query time

- Score the CV against the BM25 index → `bm25_scores` (length N).
- Embed the CV with the same model, cosine similarity against the embedding matrix → `dense_scores` (length N).
- **Fuse with Reciprocal Rank Fusion (RRF)**, k=60. RRF is more robust than weighted sums because it doesn't require score normalisation:
rrf_score(job) = 1/(k + bm25_rank(job)) + 1/(k + dense_rank(job))
- Take top 50 by RRF score. Make this configurable (`--retrieve-k`, default 50).

## Stage 2: LLM Scoring

### Model

Default to a free tier model through the already established openrouter connection. 

Concurrency: process the 50 jobs with `asyncio` + bounded semaphore (default 4 concurrent). Make this configurable.

### Prompt

For each (CV, job) pair, send a single prompt that returns structured JSON. Use this exact structure:

**System:**
> You are an expert technical recruiter assessing fit between a candidate's CV and a job description. You are blunt and calibrated: a 7/10 means genuinely strong fit, not "polite default". You ground every claim in specific evidence from the documents and never invent facts about either side.

**User:** (template, filled in per job)
Assess the fit between this candidate and this role.
<cv>
{cv_text}
</cv>
<job id="{job_id}">
{job_text}
</job>
Score the fit on these dimensions, each 1–10:

seniority_fit: Does the candidate's level (years, scope, titles) match what the role asks for? Penalise both over- and under-qualification.
tech_overlap: How well do the candidate's concrete technical skills match the must-haves and nice-to-haves?
domain_fit: Industry, problem domain, and company-stage alignment.
responsibilities_fit: Do the day-to-day responsibilities match what the candidate has actually done (vs. what they claim to want)?
location_fit: Score 10 if remote-friendly or matches candidate's location; 1 if requires relocation the candidate likely won't do; use 5 if unclear.

Then provide:

overall: 1–10 weighted holistic score, NOT a simple average. Weight tech_overlap and seniority_fit highest.
strengths: 2–4 bullet points of specific reasons this is a good match. Quote or paraphrase concrete evidence from both documents.
concerns: 1–4 bullet points of specific mismatches, gaps, or red flags. Be honest; if there are none worth mentioning, return [].
summary: One sentence (max 30 words) capturing the overall verdict.

Respond with ONLY a JSON object matching this schema, no preamble or markdown fences:
{
"seniority_fit": int,
"tech_overlap": int,
"domain_fit": int,
"responsibilities_fit": int,
"location_fit": int,
"overall": int,
"strengths": [str, ...],
"concerns": [str, ...],
"summary": str
}

### Robustness

- Validate the response with a Pydantic model or simliar. On parse failure, retry once with a "your previous response did not parse, return ONLY the JSON object" follow-up.
- On second failure, log the error and assign `overall: 0` with a `summary` of "scoring failed" so the job is excluded but the pipeline doesn't crash.
- Truncate `cv_text` and `job_text` to fit a sensible context budget (default: cap each at 6000 chars; surface as a flag).

## Output

* Matches created which can be viewed by descending order of aggregate score, with numerical scores for seniority, tech stack, domain, responsibilities, location, salary etc. 
* New route to view matches for cv and individual match with detailed analysis. 

## Flow 

* need script/entrypoint to do the CV work ahead of time
* do the CV embeddings either at upload or match request time - recommend an approach
* the LLM explainer could be done either in batch when creating matches, or, could be done on a JIT-basis when delving into the detailed match page. User experience around timings etc isn't of primary importance right now, but if an LLM call is going to take > 5 seconds, we should show a progress bar/spinner, and store the result that comes back in the db. 


## Assumptions/choices made that can be challenged

* RRF over weighted sum because you'd otherwise spend an annoying amount of time tuning weights, and RRF is famously hard to beat without supervised data.
* BGE-large as default rather than something smaller — bge-base-en-v1.5 is fine depending on what's available.
* Five scoring dimensions plus weighted overall rather than a single score, because that's where the explainability actually lives — and matches preference for honest caveats over confident overreach. The "not a simple average" instruction is deliberate; LLMs default to averaging when not told otherwise.
* Asyncio with bounded concurrency because openrouter shoult happily accept parallel requests.


Don't try to do it all in one shot. Checkpoint with me at each of the significant steps. 
If we need to include new elements to our stack to make this work well, surface options.
