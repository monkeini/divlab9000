# Task: CV Matchmaker

## Overview

Build a service that takes a CV/resume input and returns the best-matching job descriptions from a role corpus. Matching should take candidate preferences into account.

## What to build

- A **matching service** that accepts a CV and returns ranked job matches with explanations
- **Preference-aware matching** — location, salary, and work arrangement should influence results
- **Explainable output** — for each match, explain why it ranked highly, not just a score
- A **simple frontend** for testing and demo: submit a CV, view ranked matches, inspect rationale
- A **`docker-compose.yml`** so reviewers can start the full stack with a single command
- (Optional) A deployed version reachable via a public URL

Your solution should:

- Deliver a strong user experience for testing and review
- Make matching behavior easy to inspect and reason about
- Be configurable in practical ways where relevant (you choose)
- Support loading external jobs and CVs without code changes

## Corpus

You are expected to build or source your own job corpus. It should be large and varied enough that matching is non-trivial — preference filtering and role diversity should meaningfully affect results.