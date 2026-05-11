from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from jobs_api.cv_extraction import extract_cv_from_pdf
from jobs_api.database import database_path, get_connection
from jobs_api.match_analysis import MatchAnalysisError, request_match_analysis
from jobs_api.matching import retrieve_candidates
from jobs_api.models import (
    Category,
    CorpusStats,
    CvDocument,
    CvDocumentSummary,
    CvMatchDetailResponse,
    CvMatchesResponse,
    CvPreferences,
    CvStats,
    HealthResponse,
    JobDetail,
    JobsPage,
    ScrapeRun,
)
from jobs_api.repository import (
    SortOption,
    complete_match_analysis,
    complete_match_run,
    count_table,
    create_cv_document,
    create_match_run,
    create_running_match_analysis,
    cv_stats,
    fail_match_analysis,
    get_cv_document,
    get_job,
    get_match_analysis,
    get_match_detail_response,
    get_match_for_run,
    get_matches_response,
    insert_job_matches,
    latest_scrape_run,
    list_categories,
    list_cv_documents,
    list_jobs,
    list_scrape_runs,
    mark_match_analysis_running,
    mark_match_run_failed,
    update_cv_preferences,
)

app = FastAPI(
    title="Jobs Data API",
    summary="Query API for the local Adzuna-backed jobs corpus.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

Connection = Annotated[sqlite3.Connection, Depends(get_connection)]


@app.get("/", tags=["system"])
def root() -> dict[str, object]:
    return {
        "name": "Jobs Data API",
        "docs": "/docs",
        "health": "/health",
        "routes": {
            "jobs": "/jobs",
            "job_detail": "/jobs/{adzuna_id}",
            "categories": "/categories",
            "cvs": "/cvs",
            "cv_stats": "/cvs/stats",
            "cv_upload": "/cvs/upload",
            "cv_detail": "/cvs/{document_id}",
            "cv_preferences": "/cvs/{document_id}/preferences",
            "cv_matches": "/cvs/{document_id}/matches",
            "cv_match_detail": "/cvs/{document_id}/matches/{run_id}/{match_id}",
            "scrape_runs": "/scrape-runs",
            "stats": "/stats",
        },
    }


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health(connection: Connection) -> HealthResponse:
    return HealthResponse(
        status="ok",
        database_path=str(database_path()),
        job_count=count_table(connection, "jobs"),
    )


@app.get("/stats", response_model=CorpusStats, tags=["system"])
def corpus_stats(connection: Connection) -> CorpusStats:
    return CorpusStats(
        job_count=count_table(connection, "jobs"),
        category_count=count_table(connection, "categories"),
        company_count=count_table(connection, "companies"),
        location_count=count_table(connection, "locations"),
        latest_scrape_run=latest_scrape_run(connection),
    )


@app.get("/categories", response_model=list[Category], tags=["jobs"])
def categories(connection: Connection) -> list[Category]:
    return list_categories(connection)


@app.get("/jobs", response_model=JobsPage, tags=["jobs"])
def jobs(
    connection: Connection,
    q: Annotated[str | None, Query(description="Search title and description.")] = None,
    category: Annotated[str | None, Query(description="Category tag, e.g. it-jobs.")] = None,
    location: Annotated[str | None, Query(description="Location display or area text.")] = None,
    company: Annotated[str | None, Query(description="Company display-name text.")] = None,
    salary_min: Annotated[float | None, Query(ge=0)] = None,
    salary_max: Annotated[float | None, Query(ge=0)] = None,
    contract_type: Annotated[
        str | None,
        Query(description="Usually permanent or contract."),
    ] = None,
    contract_time: Annotated[
        str | None,
        Query(description="Usually full_time or part_time."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[SortOption, Query()] = "created_desc",
) -> JobsPage:
    total, results = list_jobs(
        connection,
        q=q,
        category=category,
        location=location,
        company=company,
        salary_min=salary_min,
        salary_max=salary_max,
        contract_type=contract_type,
        contract_time=contract_time,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    return JobsPage(total=total, limit=limit, offset=offset, results=results)


@app.get("/jobs/{adzuna_id}", response_model=JobDetail, tags=["jobs"])
def job_detail(
    adzuna_id: str,
    connection: Connection,
    include_raw: Annotated[
        bool,
        Query(description="Include the original Adzuna JSON payload."),
    ] = True,
) -> JobDetail:
    job = get_job(connection, adzuna_id, include_raw=include_raw)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/scrape-runs", response_model=list[ScrapeRun], tags=["scrapes"])
def scrape_runs(
    connection: Connection,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ScrapeRun]:
    return list_scrape_runs(connection, limit=limit, offset=offset)


@app.post("/cvs/upload", response_model=CvDocument, tags=["cvs"])
def upload_cv(
    connection: Connection,
    file: Annotated[UploadFile, File(description="CV/resume PDF to OCR and structure.")],
) -> CvDocument:
    if file.content_type not in {"application/pdf", "application/x-pdf"}:
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Only PDF CV uploads are supported")

    pdf_bytes = file.file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty")

    max_upload_mb = int(os.getenv("CV_UPLOAD_MAX_MB", "10"))
    max_upload_bytes = max_upload_mb * 1024 * 1024
    if len(pdf_bytes) > max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded PDF exceeds {max_upload_mb} MB limit",
        )

    try:
        extraction = extract_cv_from_pdf(pdf_bytes)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except httpx.HTTPStatusError as error:
        detail = f"OpenRouter extraction failed with HTTP {error.response.status_code}"
        raise HTTPException(status_code=502, detail=detail) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="OpenRouter extraction request failed",
        ) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    with connection:
        return create_cv_document(
            connection,
            original_filename=file.filename,
            extraction=extraction,
        )


@app.get("/cvs", response_model=list[CvDocumentSummary], tags=["cvs"])
def cvs(
    connection: Connection,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CvDocumentSummary]:
    return list_cv_documents(connection, limit=limit, offset=offset)


@app.get("/cvs/stats", response_model=CvStats, tags=["cvs"])
def cvs_stats(connection: Connection) -> CvStats:
    return cv_stats(connection)


@app.get("/cvs/{document_id}", response_model=CvDocument, tags=["cvs"])
def cv_detail(document_id: str, connection: Connection) -> CvDocument:
    document = get_cv_document(connection, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="CV document not found")
    return document


@app.patch("/cvs/{document_id}/preferences", response_model=CvDocument, tags=["cvs"])
def update_preferences(
    document_id: str,
    preferences: CvPreferences,
    connection: Connection,
) -> CvDocument:
    if (
        preferences.salary_min is not None
        and preferences.salary_max is not None
        and preferences.salary_min > preferences.salary_max
    ):
        raise HTTPException(status_code=422, detail="salary_min must be less than salary_max")

    with connection:
        document = update_cv_preferences(
            connection,
            document_id=document_id,
            preferences=preferences,
        )

    if document is None:
        raise HTTPException(status_code=404, detail="CV document not found")
    return document


@app.post("/cvs/{document_id}/matches", response_model=CvMatchesResponse, tags=["matches"])
def create_cv_matches(
    document_id: str,
    connection: Connection,
    retrieve_k: Annotated[int, Query(ge=1, le=200)] = 50,
    rrf_k: Annotated[int, Query(ge=1, le=500)] = 60,
) -> CvMatchesResponse:
    cv = get_cv_document(connection, document_id)
    if cv is None:
        raise HTTPException(status_code=404, detail="CV document not found")

    with connection:
        run = create_match_run(
            connection,
            cv_document_id=document_id,
            retrieve_count=retrieve_k,
            rrf_k=rrf_k,
        )

    try:
        candidates, metadata = retrieve_candidates(
            connection,
            cv=cv,
            retrieve_k=retrieve_k,
            rrf_k=rrf_k,
        )
    except Exception as error:
        with connection:
            mark_match_run_failed(connection, run_id=run.id, error_message=str(error))
        raise HTTPException(status_code=500, detail=f"Matching failed: {error}") from error

    try:
        with connection:
            insert_job_matches(
                connection,
                run_id=run.id,
                cv_document_id=document_id,
                matches=[asdict(candidate) for candidate in candidates],
            )
            complete_match_run(
                connection,
                run_id=run.id,
                index_fingerprint=metadata["index_fingerprint"],
                index_model=metadata["index_model"],
            )
    except Exception as error:
        with connection:
            mark_match_run_failed(connection, run_id=run.id, error_message=str(error))
        raise HTTPException(status_code=500, detail=f"Storing matches failed: {error}") from error

    response = get_matches_response(connection, cv_document_id=document_id, run_id=run.id)
    if response is None:
        raise HTTPException(status_code=500, detail="Stored match run could not be loaded")
    return response


@app.get("/cvs/{document_id}/matches", response_model=CvMatchesResponse, tags=["matches"])
def cv_matches(document_id: str, connection: Connection) -> CvMatchesResponse:
    cv = get_cv_document(connection, document_id)
    if cv is None:
        raise HTTPException(status_code=404, detail="CV document not found")

    response = get_matches_response(connection, cv_document_id=document_id)
    if response is None:
        raise HTTPException(status_code=404, detail="No successful match run found for CV")
    return response


@app.get("/cvs/{document_id}/matches/{run_id}", response_model=CvMatchesResponse, tags=["matches"])
def cv_match_run(document_id: str, run_id: int, connection: Connection) -> CvMatchesResponse:
    cv = get_cv_document(connection, document_id)
    if cv is None:
        raise HTTPException(status_code=404, detail="CV document not found")

    response = get_matches_response(connection, cv_document_id=document_id, run_id=run_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Match run not found for CV")
    return response


@app.get(
    "/cvs/{document_id}/matches/{run_id}/{match_id}",
    response_model=CvMatchDetailResponse,
    tags=["matches"],
)
def cv_match_detail(
    document_id: str,
    run_id: int,
    match_id: int,
    connection: Connection,
) -> CvMatchDetailResponse:
    response = get_match_detail_response(
        connection,
        cv_document_id=document_id,
        run_id=run_id,
        match_id=match_id,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Match not found for CV run")
    return response


@app.post(
    "/cvs/{document_id}/matches/{run_id}/{match_id}/analysis",
    response_model=CvMatchDetailResponse,
    tags=["matches"],
)
def create_or_get_match_analysis(
    document_id: str,
    run_id: int,
    match_id: int,
    connection: Connection,
) -> CvMatchDetailResponse:
    cv = get_cv_document(connection, document_id)
    if cv is None:
        raise HTTPException(status_code=404, detail="CV document not found")

    match = get_match_for_run(
        connection,
        cv_document_id=document_id,
        run_id=run_id,
        match_id=match_id,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found for CV run")

    job = get_job(connection, match.job.adzuna_id, include_raw=True)
    if job is None or not isinstance(job, JobDetail):
        raise HTTPException(status_code=404, detail="Job not found for match")

    analysis = get_match_analysis(connection, match_id=match_id)
    if analysis is not None and analysis.status == "success":
        response = get_match_detail_response(
            connection,
            cv_document_id=document_id,
            run_id=run_id,
            match_id=match_id,
        )
        if response is None:
            raise HTTPException(status_code=500, detail="Stored match analysis could not be loaded")
        return response

    with connection:
        if analysis is None:
            analysis = create_running_match_analysis(connection, match=match)
        else:
            analysis = mark_match_analysis_running(connection, analysis_id=analysis.id)

    model: str | None = None
    try:
        result, model, raw_response = request_match_analysis(cv, job)
        with connection:
            complete_match_analysis(
                connection,
                analysis_id=analysis.id,
                model=model,
                result=result.model_dump(),
                raw_response=raw_response,
            )
    except httpx.HTTPStatusError as error:
        message = f"OpenRouter analysis failed with HTTP {error.response.status_code}"
        with connection:
            fail_match_analysis(
                connection,
                analysis_id=analysis.id,
                model=model,
                error_message=message,
            )
        raise HTTPException(status_code=502, detail=message) from error
    except httpx.HTTPError as error:
        message = "OpenRouter analysis request failed"
        with connection:
            fail_match_analysis(
                connection,
                analysis_id=analysis.id,
                model=model,
                error_message=message,
            )
        raise HTTPException(status_code=502, detail=message) from error
    except RuntimeError as error:
        with connection:
            fail_match_analysis(
                connection,
                analysis_id=analysis.id,
                model=model,
                error_message=str(error),
            )
        raise HTTPException(status_code=500, detail=str(error)) from error
    except MatchAnalysisError as error:
        with connection:
            fail_match_analysis(
                connection,
                analysis_id=analysis.id,
                model=error.model,
                error_message=str(error),
                raw_response=error.raw_response,
            )
        raise HTTPException(status_code=500, detail=f"Analysis parsing failed: {error}") from error
    except ValueError as error:
        with connection:
            fail_match_analysis(
                connection,
                analysis_id=analysis.id,
                model=model,
                error_message=str(error),
            )
        raise HTTPException(status_code=500, detail=f"Analysis parsing failed: {error}") from error

    response = get_match_detail_response(
        connection,
        cv_document_id=document_id,
        run_id=run_id,
        match_id=match_id,
    )
    if response is None:
        raise HTTPException(status_code=500, detail="Stored match analysis could not be loaded")
    return response
