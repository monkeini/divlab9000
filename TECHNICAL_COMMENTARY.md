# Task: CV Matchmaker

Document your decisions, trade-offs, and scope choices.

## Early decisions

* Job domain - keep to UK, tech jobs, permenant roles. 
* Source of job corpus - try APIS/scrapability of major job sites, as single source will reduce need for normalisation/homogenisation. 
* Corpus properties - minimum 1000 varied roles
* Source of sample CVs - use my own, plus synthetic, based on real profiles if possible. Consider HN 'Who wants to be hired' threads. 
* CV Upload - allow PDF, and use web service/local model to do OCR. Store data as structured blob.

### User preferences to capture:
* Location
* Salary range
* Working arrangement
* Industry or keyword? 

### Matching:
* Consider something applicable for ~1m users and ~1m jobs. I.e. cannot afford something that needs to do n*m expensive (LLM) comparisons. Full LLM for everything might find hidden quirky gems, but simply too computationally expensive. 
* Consider lexical and embedding approaches, potentially then filtered for llm-powered deep dives.
* Present some high-level score if possible, then dig into the dimensions.

### Out of scope:
* User accounts, persistent preferences etc.
* UX for user to correct/update data extracted from CV
* Asynchronous upload/update of CV/matches

### Tech choices
* Python, uv, ruff, FastAPI for backend 
* SQLlite for job data - nothing fancy needed here, keep it simple 
* Vite + React + TypeScript for frontend, nothing too opinionated until we need to make a call on something that needs iterate
* OpenRouter for LLM use, using free tier models 


## DevLog 

* Found Adzuna API that looks suitable. Free key, paginated, good filter options. 
* Looking at categories, I will filter by industry 'it-jobs'
* Had Codex suggest schema for the job data, create a migration script to create said schema in SQLite, write the process to iterate over all matching jobs and save them to the db. 
* Scrape it-jobs - 100 pages @ 50 jobs per page - rate-limit hit at that point.
* Create a FastAPI API on top for use in the front end
* Build the CV PDF ocr parser. Prompt Codex to build, relying on free tier open router models 
* Refine the experience of upload to present the fully parsed cv when completed
* Wrote full matching system prompt as md file and have codex attack
* Run process to calc embeddings etc
* Reviewed UI output and made tweaks
* Kicked off the build of the llm-powered 'dig deeper' stage 
* Tweaked to fix 'no content' edgecase 
* Update of README.md to reflect final state 
* Deployed to VPS

