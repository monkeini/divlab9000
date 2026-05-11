from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Literal

from jobs_api.cv_extraction import CvExtractionResult
from jobs_api.models import (
    Category,
    Company,
    CvDocument,
    CvDocumentSummary,
    CvJobMatch,
    CvMatchAnalysis,
    CvMatchDetailResponse,
    CvMatchesResponse,
    CvMatchRun,
    CvPreferences,
    CvStats,
    JobDetail,
    JobSummary,
    Location,
    ScrapeRun,
    StructuredCv,
)

SortOption = Literal[
    "created_desc",
    "created_asc",
    "salary_max_desc",
    "salary_min_desc",
    "title_asc",
]

SORT_SQL: dict[str, str] = {
    "created_desc": "j.created_at DESC, j.adzuna_id DESC",
    "created_asc": "j.created_at ASC, j.adzuna_id ASC",
    "salary_max_desc": "j.salary_max DESC, j.adzuna_id DESC",
    "salary_min_desc": "j.salary_min DESC, j.adzuna_id DESC",
    "title_asc": "j.title COLLATE NOCASE ASC, j.adzuna_id ASC",
}

JOB_SELECT = """
    SELECT
        j.adzuna_id,
        j.title,
        j.description,
        j.redirect_url,
        j.adref,
        j.created_at,
        j.scraped_at,
        j.updated_at,
        j.salary_min,
        j.salary_max,
        j.salary_is_predicted,
        j.contract_type,
        j.contract_time,
        j.latitude,
        j.longitude,
        j.raw_json,
        c.tag AS category_tag,
        c.label AS category_label,
        co.id AS company_id,
        co.display_name AS company_display_name,
        l.id AS location_id,
        l.display_name AS location_display_name,
        l.area_json AS location_area_json,
        l.latitude AS location_latitude,
        l.longitude AS location_longitude
    FROM jobs j
    LEFT JOIN categories c ON c.tag = j.category_tag
    LEFT JOIN companies co ON co.id = j.company_id
    LEFT JOIN locations l ON l.id = j.location_id
"""


def decode_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def row_to_job(row: sqlite3.Row, *, include_raw: bool = False) -> JobSummary | JobDetail:
    category = None
    if row["category_tag"]:
        category = Category(tag=row["category_tag"], label=row["category_label"], job_count=0)

    company = None
    if row["company_id"]:
        company = Company(id=row["company_id"], display_name=row["company_display_name"])

    location = None
    if row["location_id"]:
        location = Location(
            id=row["location_id"],
            display_name=row["location_display_name"],
            area=decode_json(row["location_area_json"], []),
            latitude=row["location_latitude"],
            longitude=row["location_longitude"],
        )

    payload = {
        "adzuna_id": row["adzuna_id"],
        "title": row["title"],
        "description": row["description"],
        "redirect_url": row["redirect_url"],
        "created_at": row["created_at"],
        "scraped_at": row["scraped_at"],
        "updated_at": row["updated_at"],
        "salary_min": row["salary_min"],
        "salary_max": row["salary_max"],
        "salary_is_predicted": bool(row["salary_is_predicted"]),
        "contract_type": row["contract_type"],
        "contract_time": row["contract_time"],
        "category": category,
        "company": company,
        "location": location,
        "latitude": row["latitude"],
        "longitude": row["longitude"],
    }
    if include_raw:
        return JobDetail(
            **payload,
            adref=row["adref"],
            raw_json=decode_json(row["raw_json"], {}),
        )
    return JobSummary(**payload)


def build_job_filters(
    *,
    q: str | None,
    category: str | None,
    location: str | None,
    company: str | None,
    salary_min: float | None,
    salary_max: float | None,
    contract_type: str | None,
    contract_time: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if q:
        clauses.append("(j.title LIKE ? OR j.description LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if category:
        clauses.append("j.category_tag = ?")
        params.append(category)
    if location:
        clauses.append("(l.display_name LIKE ? OR l.area_json LIKE ?)")
        params.extend([f"%{location}%", f"%{location}%"])
    if company:
        clauses.append("co.display_name LIKE ?")
        params.append(f"%{company}%")
    if salary_min is not None:
        clauses.append("j.salary_max >= ?")
        params.append(salary_min)
    if salary_max is not None:
        clauses.append("j.salary_min <= ?")
        params.append(salary_max)
    if contract_type:
        clauses.append("j.contract_type = ?")
        params.append(contract_type)
    if contract_time:
        clauses.append("j.contract_time = ?")
        params.append(contract_time)

    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def list_jobs(
    connection: sqlite3.Connection,
    *,
    q: str | None,
    category: str | None,
    location: str | None,
    company: str | None,
    salary_min: float | None,
    salary_max: float | None,
    contract_type: str | None,
    contract_time: str | None,
    limit: int,
    offset: int,
    sort: SortOption,
) -> tuple[int, list[JobSummary]]:
    where_sql, params = build_job_filters(
        q=q,
        category=category,
        location=location,
        company=company,
        salary_min=salary_min,
        salary_max=salary_max,
        contract_type=contract_type,
        contract_time=contract_time,
    )
    count_sql = f"""
        SELECT COUNT(*)
        FROM jobs j
        LEFT JOIN companies co ON co.id = j.company_id
        LEFT JOIN locations l ON l.id = j.location_id
        {where_sql}
    """
    total = int(connection.execute(count_sql, params).fetchone()[0])

    rows = connection.execute(
        f"""
        {JOB_SELECT}
        {where_sql}
        ORDER BY {SORT_SQL[sort]}
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return total, [row_to_job(row) for row in rows]


def get_job(
    connection: sqlite3.Connection,
    adzuna_id: str,
    *,
    include_raw: bool,
) -> JobDetail | JobSummary | None:
    row = connection.execute(
        f"{JOB_SELECT} WHERE j.adzuna_id = ?",
        (adzuna_id,),
    ).fetchone()
    if not row:
        return None
    return row_to_job(row, include_raw=include_raw)


def list_categories(connection: sqlite3.Connection) -> list[Category]:
    rows = connection.execute(
        """
        SELECT c.tag, c.label, COUNT(j.adzuna_id) AS job_count
        FROM categories c
        LEFT JOIN jobs j ON j.category_tag = c.tag
        GROUP BY c.tag, c.label
        ORDER BY c.label COLLATE NOCASE
        """
    ).fetchall()
    return [
        Category(tag=row["tag"], label=row["label"], job_count=row["job_count"])
        for row in rows
    ]


def row_to_scrape_run(row: sqlite3.Row) -> ScrapeRun:
    return ScrapeRun(
        id=row["id"],
        provider=row["provider"],
        country=row["country"],
        query_params=decode_json(row["query_params_json"], {}),
        start_page=row["start_page"],
        end_page=row["end_page"],
        requested_results_per_page=row["requested_results_per_page"],
        total_count=row["total_count"],
        mean_salary=row["mean_salary"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
    )


def list_scrape_runs(connection: sqlite3.Connection, *, limit: int, offset: int) -> list[ScrapeRun]:
    rows = connection.execute(
        """
        SELECT *
        FROM scrape_runs
        ORDER BY started_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [row_to_scrape_run(row) for row in rows]


def latest_scrape_run(connection: sqlite3.Connection) -> ScrapeRun | None:
    row = connection.execute(
        """
        SELECT *
        FROM scrape_runs
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    return row_to_scrape_run(row)


def count_table(connection: sqlite3.Connection, table_name: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def row_to_cv_document(row: sqlite3.Row) -> CvDocument:
    structured = decode_json(row["structured_json"], {})
    provider_response = decode_json(row["provider_response_json"], {})
    return CvDocument(
        id=row["id"],
        original_filename=row["original_filename"],
        file_sha256=row["file_sha256"],
        file_size_bytes=row["file_size_bytes"],
        page_count=row["page_count"],
        model=row["model"],
        openrouter_duration_seconds=provider_response.get("openrouter_duration_seconds"),
        preferences=row_to_cv_preferences(row),
        plain_text=row["plain_text"],
        structured=StructuredCv(**structured),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def row_to_cv_summary(row: sqlite3.Row) -> CvDocumentSummary:
    structured = decode_json(row["structured_json"], {})
    provider_response = decode_json(row["provider_response_json"], {})
    return CvDocumentSummary(
        id=row["id"],
        original_filename=row["original_filename"],
        file_sha256=row["file_sha256"],
        file_size_bytes=row["file_size_bytes"],
        page_count=row["page_count"],
        model=row["model"],
        openrouter_duration_seconds=provider_response.get("openrouter_duration_seconds"),
        preferences=row_to_cv_preferences(row),
        candidate_name=structured.get("name"),
        candidate_email=structured.get("email"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def row_to_cv_preferences(row: sqlite3.Row) -> CvPreferences:
    return CvPreferences(
        preferred_location=row["preferred_location"],
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        working_arrangements=decode_json(row["working_arrangements_json"], []),
        industry_keyword=row["industry_keyword"],
    )


def create_cv_document(
    connection: sqlite3.Connection,
    *,
    original_filename: str | None,
    extraction: CvExtractionResult,
) -> CvDocument:
    document_id = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO cv_documents (
            id,
            original_filename,
            file_sha256,
            file_size_bytes,
            page_count,
            model,
            plain_text,
            structured_json,
            provider_response_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            original_filename,
            extraction.file_sha256,
            extraction.file_size_bytes,
            extraction.page_count,
            extraction.model,
            extraction.plain_text,
            json.dumps(extraction.structured, ensure_ascii=False, sort_keys=True),
            json.dumps(extraction.provider_response, ensure_ascii=False, sort_keys=True),
        ),
    )
    row = connection.execute(
        "SELECT * FROM cv_documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    return row_to_cv_document(row)


def update_cv_preferences(
    connection: sqlite3.Connection,
    *,
    document_id: str,
    preferences: CvPreferences,
) -> CvDocument | None:
    existing = connection.execute(
        "SELECT id FROM cv_documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if not existing:
        return None

    connection.execute(
        """
        UPDATE cv_documents
        SET preferred_location = ?,
            salary_min = ?,
            salary_max = ?,
            working_arrangements_json = ?,
            industry_keyword = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (
            preferences.preferred_location,
            preferences.salary_min,
            preferences.salary_max,
            json.dumps(preferences.working_arrangements, sort_keys=True),
            preferences.industry_keyword,
            document_id,
        ),
    )
    return get_cv_document(connection, document_id)


def get_cv_document(connection: sqlite3.Connection, document_id: str) -> CvDocument | None:
    row = connection.execute(
        "SELECT * FROM cv_documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if not row:
        return None
    return row_to_cv_document(row)


def list_cv_documents(
    connection: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
) -> list[CvDocumentSummary]:
    rows = connection.execute(
        """
        SELECT *
        FROM cv_documents
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [row_to_cv_summary(row) for row in rows]


def cv_stats(connection: sqlite3.Connection) -> CvStats:
    row = connection.execute(
        """
        SELECT
            COUNT(*) AS cv_count,
            MAX(created_at) AS latest_upload_at,
            AVG(page_count) AS average_page_count
        FROM cv_documents
        """
    ).fetchone()
    provider_rows = connection.execute(
        "SELECT provider_response_json FROM cv_documents"
    ).fetchall()
    durations = [
        decoded["openrouter_duration_seconds"]
        for decoded in (
            decode_json(provider_row["provider_response_json"], {})
            for provider_row in provider_rows
        )
        if isinstance(decoded.get("openrouter_duration_seconds"), (int, float))
    ]
    average_duration = None
    if durations:
        average_duration = round(sum(durations) / len(durations), 3)

    average_page_count = row["average_page_count"]
    if average_page_count is not None:
        average_page_count = round(float(average_page_count), 2)

    return CvStats(
        cv_count=row["cv_count"],
        latest_upload_at=row["latest_upload_at"],
        average_openrouter_duration_seconds=average_duration,
        average_page_count=average_page_count,
        job_count=count_table(connection, "jobs"),
    )


def row_to_match_run(row: sqlite3.Row) -> CvMatchRun:
    return CvMatchRun(
        id=row["id"],
        cv_document_id=row["cv_document_id"],
        status=row["status"],
        retrieve_count=row["retrieve_count"],
        rrf_k=row["rrf_k"],
        index_fingerprint=row["index_fingerprint"],
        index_model=row["index_model"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
    )


def create_match_run(
    connection: sqlite3.Connection,
    *,
    cv_document_id: str,
    retrieve_count: int,
    rrf_k: int,
) -> CvMatchRun:
    cursor = connection.execute(
        """
        INSERT INTO cv_match_runs (cv_document_id, status, retrieve_count, rrf_k)
        VALUES (?, 'running', ?, ?)
        """,
        (cv_document_id, retrieve_count, rrf_k),
    )
    row = connection.execute(
        "SELECT * FROM cv_match_runs WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return row_to_match_run(row)


def mark_match_run_failed(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    error_message: str,
) -> CvMatchRun:
    connection.execute(
        """
        UPDATE cv_match_runs
        SET status = 'failed',
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            error_message = ?
        WHERE id = ?
        """,
        (error_message, run_id),
    )
    row = connection.execute(
        "SELECT * FROM cv_match_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    return row_to_match_run(row)


def complete_match_run(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    index_fingerprint: str,
    index_model: str,
) -> CvMatchRun:
    connection.execute(
        """
        UPDATE cv_match_runs
        SET status = 'success',
            index_fingerprint = ?,
            index_model = ?,
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (index_fingerprint, index_model, run_id),
    )
    row = connection.execute(
        "SELECT * FROM cv_match_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    return row_to_match_run(row)


def insert_job_matches(
    connection: sqlite3.Connection,
    *,
    run_id: int,
    cv_document_id: str,
    matches: list[dict[str, Any]],
) -> None:
    connection.executemany(
        """
        INSERT INTO cv_job_matches (
            run_id,
            cv_document_id,
            job_id,
            rank,
            bm25_rank,
            dense_rank,
            rrf_score,
            bm25_score,
            dense_score,
            preference_filters_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                run_id,
                cv_document_id,
                match["job_id"],
                match["rank"],
                match["bm25_rank"],
                match["dense_rank"],
                match["rrf_score"],
                match["bm25_score"],
                match["dense_score"],
                json.dumps(match["preference_filters"], sort_keys=True),
            )
            for match in matches
        ],
    )


def row_to_cv_job_match(row: sqlite3.Row) -> CvJobMatch:
    return CvJobMatch(
        id=row["match_id"],
        run_id=row["run_id"],
        cv_document_id=row["cv_document_id"],
        job=row_to_job(row),
        rank=row["rank"],
        bm25_rank=row["bm25_rank"],
        dense_rank=row["dense_rank"],
        rrf_score=row["rrf_score"],
        bm25_score=row["bm25_score"],
        dense_score=row["dense_score"],
        preference_filters=decode_json(row["preference_filters_json"], {}),
        created_at=row["match_created_at"],
    )


def row_to_cv_match_analysis(row: sqlite3.Row) -> CvMatchAnalysis:
    return CvMatchAnalysis(
        id=row["id"],
        match_id=row["match_id"],
        run_id=row["run_id"],
        cv_document_id=row["cv_document_id"],
        job_id=row["job_id"],
        status=row["status"],
        model=row["model"],
        seniority_fit=row["seniority_fit"],
        tech_overlap=row["tech_overlap"],
        domain_fit=row["domain_fit"],
        responsibilities_fit=row["responsibilities_fit"],
        location_fit=row["location_fit"],
        overall=row["overall"],
        strengths=decode_json(row["strengths_json"], []),
        concerns=decode_json(row["concerns_json"], []),
        summary=row["summary"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_message=row["error_message"],
    )


def get_match_run(connection: sqlite3.Connection, run_id: int) -> CvMatchRun | None:
    row = connection.execute(
        "SELECT * FROM cv_match_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        return None
    return row_to_match_run(row)


def latest_successful_match_run(
    connection: sqlite3.Connection,
    *,
    cv_document_id: str,
) -> CvMatchRun | None:
    row = connection.execute(
        """
        SELECT *
        FROM cv_match_runs
        WHERE cv_document_id = ? AND status = 'success'
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (cv_document_id,),
    ).fetchone()
    if not row:
        return None
    return row_to_match_run(row)


def list_matches_for_run(
    connection: sqlite3.Connection,
    *,
    run_id: int,
) -> list[CvJobMatch]:
    rows = connection.execute(
        f"""
        SELECT
            m.id AS match_id,
            m.run_id,
            m.cv_document_id,
            m.rank,
            m.bm25_rank,
            m.dense_rank,
            m.rrf_score,
            m.bm25_score,
            m.dense_score,
            m.preference_filters_json,
            m.created_at AS match_created_at,
            job_rows.*
        FROM cv_job_matches m
        JOIN ({JOB_SELECT}) AS job_rows ON job_rows.adzuna_id = m.job_id
        WHERE m.run_id = ?
        ORDER BY m.rank ASC
        """,
        (run_id,),
    ).fetchall()
    return [row_to_cv_job_match(row) for row in rows]


def get_matches_response(
    connection: sqlite3.Connection,
    *,
    cv_document_id: str,
    run_id: int | None = None,
) -> CvMatchesResponse | None:
    run = get_match_run(connection, run_id) if run_id is not None else latest_successful_match_run(
        connection,
        cv_document_id=cv_document_id,
    )
    if run is None or run.cv_document_id != cv_document_id:
        return None
    return CvMatchesResponse(run=run, matches=list_matches_for_run(connection, run_id=run.id))


def get_match_for_run(
    connection: sqlite3.Connection,
    *,
    cv_document_id: str,
    run_id: int,
    match_id: int,
) -> CvJobMatch | None:
    rows = connection.execute(
        f"""
        SELECT
            m.id AS match_id,
            m.run_id,
            m.cv_document_id,
            m.rank,
            m.bm25_rank,
            m.dense_rank,
            m.rrf_score,
            m.bm25_score,
            m.dense_score,
            m.preference_filters_json,
            m.created_at AS match_created_at,
            job_rows.*
        FROM cv_job_matches m
        JOIN ({JOB_SELECT}) AS job_rows ON job_rows.adzuna_id = m.job_id
        WHERE m.cv_document_id = ? AND m.run_id = ? AND m.id = ?
        """,
        (cv_document_id, run_id, match_id),
    ).fetchall()
    if not rows:
        return None
    return row_to_cv_job_match(rows[0])


def get_match_analysis(
    connection: sqlite3.Connection,
    *,
    match_id: int,
) -> CvMatchAnalysis | None:
    row = connection.execute(
        "SELECT * FROM cv_match_analyses WHERE match_id = ?",
        (match_id,),
    ).fetchone()
    if not row:
        return None
    return row_to_cv_match_analysis(row)


def create_running_match_analysis(
    connection: sqlite3.Connection,
    *,
    match: CvJobMatch,
) -> CvMatchAnalysis:
    cursor = connection.execute(
        """
        INSERT INTO cv_match_analyses (
            match_id,
            run_id,
            cv_document_id,
            job_id,
            status
        )
        VALUES (?, ?, ?, ?, 'running')
        """,
        (match.id, match.run_id, match.cv_document_id, match.job.adzuna_id),
    )
    row = connection.execute(
        "SELECT * FROM cv_match_analyses WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return row_to_cv_match_analysis(row)


def mark_match_analysis_running(
    connection: sqlite3.Connection,
    *,
    analysis_id: int,
) -> CvMatchAnalysis:
    connection.execute(
        """
        UPDATE cv_match_analyses
        SET status = 'running',
            started_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            finished_at = NULL,
            error_message = NULL
        WHERE id = ?
        """,
        (analysis_id,),
    )
    row = connection.execute(
        "SELECT * FROM cv_match_analyses WHERE id = ?",
        (analysis_id,),
    ).fetchone()
    return row_to_cv_match_analysis(row)


def complete_match_analysis(
    connection: sqlite3.Connection,
    *,
    analysis_id: int,
    model: str,
    result: dict[str, Any],
    raw_response: dict[str, Any],
) -> CvMatchAnalysis:
    connection.execute(
        """
        UPDATE cv_match_analyses
        SET status = 'success',
            model = ?,
            seniority_fit = ?,
            tech_overlap = ?,
            domain_fit = ?,
            responsibilities_fit = ?,
            location_fit = ?,
            overall = ?,
            strengths_json = ?,
            concerns_json = ?,
            summary = ?,
            raw_response_json = ?,
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            error_message = NULL
        WHERE id = ?
        """,
        (
            model,
            result["seniority_fit"],
            result["tech_overlap"],
            result["domain_fit"],
            result["responsibilities_fit"],
            result["location_fit"],
            result["overall"],
            json.dumps(result["strengths"], sort_keys=True),
            json.dumps(result["concerns"], sort_keys=True),
            result["summary"],
            json.dumps(raw_response, ensure_ascii=False, sort_keys=True),
            analysis_id,
        ),
    )
    row = connection.execute(
        "SELECT * FROM cv_match_analyses WHERE id = ?",
        (analysis_id,),
    ).fetchone()
    return row_to_cv_match_analysis(row)


def fail_match_analysis(
    connection: sqlite3.Connection,
    *,
    analysis_id: int,
    model: str | None,
    error_message: str,
    raw_response: dict[str, Any] | None = None,
) -> CvMatchAnalysis:
    connection.execute(
        """
        UPDATE cv_match_analyses
        SET status = 'failed',
            model = ?,
            error_message = ?,
            raw_response_json = ?,
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (
            model,
            error_message,
            json.dumps(raw_response, ensure_ascii=False, sort_keys=True)
            if raw_response is not None
            else None,
            analysis_id,
        ),
    )
    row = connection.execute(
        "SELECT * FROM cv_match_analyses WHERE id = ?",
        (analysis_id,),
    ).fetchone()
    return row_to_cv_match_analysis(row)


def get_match_detail_response(
    connection: sqlite3.Connection,
    *,
    cv_document_id: str,
    run_id: int,
    match_id: int,
) -> CvMatchDetailResponse | None:
    run = get_match_run(connection, run_id)
    if run is None or run.cv_document_id != cv_document_id:
        return None

    match = get_match_for_run(
        connection,
        cv_document_id=cv_document_id,
        run_id=run_id,
        match_id=match_id,
    )
    if match is None:
        return None

    job = get_job(connection, match.job.adzuna_id, include_raw=True)
    if job is None or not isinstance(job, JobDetail):
        return None

    return CvMatchDetailResponse(
        run=run,
        match=match,
        job=job,
        analysis=get_match_analysis(connection, match_id=match_id),
    )
