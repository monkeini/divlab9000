from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Category(BaseModel):
    tag: str
    label: str
    job_count: int = 0


class Company(BaseModel):
    id: int
    display_name: str


class Location(BaseModel):
    id: int
    display_name: str
    area: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None


class JobSummary(BaseModel):
    adzuna_id: str
    title: str
    description: str | None = None
    redirect_url: str | None = None
    created_at: str | None = None
    scraped_at: str
    updated_at: str
    salary_min: float | None = None
    salary_max: float | None = None
    salary_is_predicted: bool
    contract_type: str | None = None
    contract_time: str | None = None
    category: Category | None = None
    company: Company | None = None
    location: Location | None = None
    latitude: float | None = None
    longitude: float | None = None


class JobDetail(JobSummary):
    adref: str | None = None
    raw_json: dict[str, Any] | None = None


class JobsPage(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[JobSummary]


class ScrapeRun(BaseModel):
    id: int
    provider: str
    country: str
    query_params: dict[str, Any]
    start_page: int
    end_page: int | None = None
    requested_results_per_page: int
    total_count: int | None = None
    mean_salary: float | None = None
    status: Literal["running", "success", "failed"]
    started_at: str
    finished_at: str | None = None
    error_message: str | None = None


class CorpusStats(BaseModel):
    job_count: int
    category_count: int
    company_count: int
    location_count: int
    latest_scrape_run: ScrapeRun | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database_path: str
    job_count: int

    model_config = ConfigDict(protected_namespaces=())


class StructuredCv(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    salary_expectation: str | None = None


WorkingArrangement = Literal["on_site", "hybrid", "remote"]


class CvPreferences(BaseModel):
    preferred_location: str | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    working_arrangements: list[WorkingArrangement] = Field(default_factory=list)
    industry_keyword: str | None = None


class CvDocument(BaseModel):
    id: str
    original_filename: str | None = None
    file_sha256: str
    file_size_bytes: int
    page_count: int
    model: str
    openrouter_duration_seconds: float | None = None
    preferences: CvPreferences = Field(default_factory=CvPreferences)
    plain_text: str
    structured: StructuredCv
    created_at: str
    updated_at: str


class CvDocumentSummary(BaseModel):
    id: str
    original_filename: str | None = None
    file_sha256: str
    file_size_bytes: int
    page_count: int
    model: str
    openrouter_duration_seconds: float | None = None
    preferences: CvPreferences = Field(default_factory=CvPreferences)
    candidate_name: str | None = None
    candidate_email: str | None = None
    created_at: str
    updated_at: str


class CvStats(BaseModel):
    cv_count: int
    latest_upload_at: str | None = None
    average_openrouter_duration_seconds: float | None = None
    average_page_count: float | None = None
    job_count: int


class CvMatchRun(BaseModel):
    id: int
    cv_document_id: str
    status: Literal["running", "success", "failed"]
    retrieve_count: int
    rrf_k: int
    index_fingerprint: str | None = None
    index_model: str | None = None
    started_at: str
    finished_at: str | None = None
    error_message: str | None = None


class CvJobMatch(BaseModel):
    id: int
    run_id: int
    cv_document_id: str
    job: JobSummary
    rank: int
    bm25_rank: int | None = None
    dense_rank: int | None = None
    rrf_score: float
    bm25_score: float
    dense_score: float
    preference_filters: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class CvMatchesResponse(BaseModel):
    run: CvMatchRun
    matches: list[CvJobMatch]


class CvMatchAnalysis(BaseModel):
    id: int
    match_id: int
    run_id: int
    cv_document_id: str
    job_id: str
    status: Literal["running", "success", "failed"]
    model: str | None = None
    seniority_fit: int | None = None
    tech_overlap: int | None = None
    domain_fit: int | None = None
    responsibilities_fit: int | None = None
    location_fit: int | None = None
    overall: int | None = None
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    summary: str | None = None
    started_at: str
    finished_at: str | None = None
    error_message: str | None = None


class CvMatchDetailResponse(BaseModel):
    run: CvMatchRun
    match: CvJobMatch
    job: JobDetail
    analysis: CvMatchAnalysis | None = None
