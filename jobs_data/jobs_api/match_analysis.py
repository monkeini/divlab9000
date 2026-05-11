from __future__ import annotations

import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

from jobs_api.cv_extraction import (
    DEFAULT_MODEL,
    PROJECT_DIR,
    REPO_DIR,
    assistant_content,
    parse_json_content,
    request_openrouter,
)
from jobs_api.models import CvDocument, JobDetail

ANALYSIS_SYSTEM_PROMPT = """
You are an expert technical recruiter assessing fit between a candidate's CV and a job description.
You are blunt and calibrated: a 7/10 means genuinely strong fit, not a polite default.
Ground every claim in specific evidence from the documents and never invent facts about either side.
""".strip()


class MatchAnalysisError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        model: str,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.model = model
        self.raw_response = raw_response


class MatchAnalysisResult(BaseModel):
    seniority_fit: int = Field(ge=1, le=10)
    tech_overlap: int = Field(ge=1, le=10)
    domain_fit: int = Field(ge=1, le=10)
    responsibilities_fit: int = Field(ge=1, le=10)
    location_fit: int = Field(ge=1, le=10)
    overall: int = Field(ge=1, le=10)
    strengths: list[str] = Field(default_factory=list, min_length=0, max_length=4)
    concerns: list[str] = Field(default_factory=list, min_length=0, max_length=4)
    summary: str

    @field_validator("strengths", "concerns")
    @classmethod
    def clean_list(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("summary")
    @classmethod
    def clean_summary(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("summary must not be empty")
        return cleaned


def load_analysis_settings() -> tuple[str, str]:
    for env_file in (
        PROJECT_DIR / ".env",
        PROJECT_DIR / ".enmv",
        REPO_DIR / ".env",
        REPO_DIR / ".enmv",
    ):
        if env_file.exists():
            load_dotenv(env_file, override=False)

    api_key = os.getenv("OPENROUTER_KEY") or os.getenv("OPEN_ROUTER_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_KEY or OPEN_ROUTER_KEY in environment")

    model = os.getenv("OPENROUTER_ANALYSIS_MODEL") or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    return api_key, model


def truncate_text(text: str | None, limit: int = 6000) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "\n[truncated]"


def cv_text(cv: CvDocument) -> str:
    structured = cv.structured
    parts = [
        cv.plain_text,
        f"Summary: {structured.summary}" if structured.summary else "",
        f"Skills: {', '.join(structured.skills)}" if structured.skills else "",
        f"Preferred roles: {', '.join(structured.preferred_roles)}"
        if structured.preferred_roles
        else "",
        f"Preferred locations: {', '.join(structured.preferred_locations)}"
        if structured.preferred_locations
        else "",
        f"User preferred location: {cv.preferences.preferred_location}"
        if cv.preferences.preferred_location
        else "",
        f"User salary range: {cv.preferences.salary_min} - {cv.preferences.salary_max}"
        if cv.preferences.salary_min or cv.preferences.salary_max
        else "",
        f"User working arrangements: {', '.join(cv.preferences.working_arrangements)}"
        if cv.preferences.working_arrangements
        else "",
        f"User industry keyword: {cv.preferences.industry_keyword}"
        if cv.preferences.industry_keyword
        else "",
    ]
    return truncate_text("\n".join(part for part in parts if part))


def job_text(job: JobDetail) -> str:
    company = job.company.display_name if job.company else "Not listed"
    location = job.location.display_name if job.location else "Not listed"
    category = job.category.label if job.category else "Not listed"
    salary = "Not listed"
    if job.salary_min is not None or job.salary_max is not None:
        salary = f"{job.salary_min or 'unknown'} - {job.salary_max or 'unknown'}"

    parts = [
        f"Title: {job.title}",
        f"Company: {company}",
        f"Location: {location}",
        f"Category: {category}",
        f"Salary: {salary}",
        f"Contract type: {job.contract_type or 'Not listed'}",
        f"Contract time: {job.contract_time or 'Not listed'}",
        "Description:",
        job.description or "",
    ]
    return truncate_text("\n".join(parts))


def user_prompt(cv: CvDocument, job: JobDetail) -> str:
    return f"""
Assess the fit between this candidate and this role.

<cv>
{cv_text(cv)}
</cv>

<job id="{job.adzuna_id}">
{job_text(job)}
</job>

Score the fit on these dimensions, each 1-10:

seniority_fit: Does the candidate's level match what the role asks for?
Penalise both over- and under-qualification.
tech_overlap: How well do the candidate's concrete technical skills match the role requirements?
domain_fit: Industry, problem domain, and company-stage alignment.
responsibilities_fit: Do the day-to-day responsibilities match what the candidate has actually done?
location_fit: Score 10 if remote-friendly or matches candidate location.
Score 1 if relocation is likely required; use 5 if unclear.

Then provide:

overall: 1-10 weighted holistic score, NOT a simple average.
Weight tech_overlap and seniority_fit highest.
strengths: 2-4 bullets with specific evidence from both documents.
concerns: 1-4 bullets with specific mismatches, gaps, or red flags.
Return [] if none are worth mentioning.
summary: One sentence, max 30 words.

Respond with ONLY a JSON object matching this schema:
{{
  "seniority_fit": 1,
  "tech_overlap": 1,
  "domain_fit": 1,
  "responsibilities_fit": 1,
  "location_fit": 1,
  "overall": 1,
  "strengths": ["..."],
  "concerns": ["..."],
  "summary": "..."
}}
""".strip()


def build_analysis_payload(model: str, cv: CvDocument, job: JobDetail) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(cv, job)},
        ],
        "temperature": 0,
        "max_tokens": 1400,
        "response_format": {"type": "json_object"},
    }


def parse_analysis_response(response_payload: dict[str, Any]) -> MatchAnalysisResult:
    content = assistant_content(response_payload)
    if not content.strip():
        raise ValueError("OpenRouter response text was empty")
    parsed = parse_json_content(content)
    return MatchAnalysisResult.model_validate(parsed)


def response_diagnostic(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices") or []
    if not choices:
        return "OpenRouter response did not include choices"
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    finish_reason = choice.get("finish_reason") or "unknown"
    if content is None:
        keys = ", ".join(sorted(str(key) for key in message.keys())) or "none"
        return (
            "OpenRouter response did not include message content "
            f"(finish_reason={finish_reason}, message_keys={keys})"
        )
    if isinstance(content, list) and not any(
        isinstance(part, dict) and part.get("text") for part in content
    ):
        return (
            "OpenRouter response content did not include text parts "
            f"(finish_reason={finish_reason})"
        )
    return f"OpenRouter response could not be parsed (finish_reason={finish_reason})"


def request_match_analysis(
    cv: CvDocument,
    job: JobDetail,
) -> tuple[MatchAnalysisResult, str, dict[str, Any]]:
    api_key, model = load_analysis_settings()
    payload = build_analysis_payload(model, cv, job)
    started_at = time.perf_counter()
    response_payload = request_openrouter(api_key, payload)
    duration = round(time.perf_counter() - started_at, 3)

    try:
        analysis = parse_analysis_response(response_payload)
    except (ValueError, ValidationError) as first_error:
        retry_payload = {
            "model": model,
            "messages": [
                *payload["messages"],
                {
                    "role": "user",
                    "content": (
                        f"Your previous response did not parse: {first_error}. "
                        "Return ONLY the JSON object with the exact requested schema."
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": 1400,
            "response_format": {"type": "json_object"},
        }
        response_payload = request_openrouter(api_key, retry_payload)
        try:
            analysis = parse_analysis_response(response_payload)
        except (ValueError, ValidationError) as retry_error:
            diagnostic = response_diagnostic(response_payload)
            raise MatchAnalysisError(
                f"{diagnostic}: {retry_error}",
                model=model,
                raw_response=response_payload,
            ) from retry_error

    raw_response = {
        "openrouter_duration_seconds": duration,
        "response": response_payload,
    }
    return analysis, model, json.loads(json.dumps(raw_response))
