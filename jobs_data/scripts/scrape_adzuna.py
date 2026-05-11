from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from migrate import DEFAULT_DB_PATH, apply_migrations, connect

API_ROOT = "https://api.adzuna.com/v1/api/jobs"
PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = PROJECT_DIR.parent


def load_credentials() -> tuple[str, str]:
    for env_file in (
        PROJECT_DIR / ".env",
        PROJECT_DIR / ".enmv",
        REPO_DIR / ".env",
        REPO_DIR / ".enmv",
    ):
        if env_file.exists():
            load_dotenv(env_file, override=False)

    app_id = os.getenv("APP_ID")
    app_key = os.getenv("APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("Missing APP_ID or APP_KEY in environment, .env, or .enmv")
    return app_id, app_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Adzuna job search results into SQLite.",
    )
    parser.add_argument("--country", default="gb", help="Adzuna country code. Default: gb.")
    parser.add_argument("--category", help="Adzuna category tag, e.g. it-jobs.")
    parser.add_argument("--what", help="Keyword/title query, e.g. 'software engineer'.")
    parser.add_argument("--where", dest="where_", help="Location query, e.g. London.")
    parser.add_argument("--what-exclude", help="Keyword to exclude from results.")
    parser.add_argument("--salary-min", type=int, help="Minimum salary filter.")
    parser.add_argument("--salary-max", type=int, help="Maximum salary filter.")
    parser.add_argument("--full-time", action="store_true", help="Limit to full-time roles.")
    parser.add_argument("--part-time", action="store_true", help="Limit to part-time roles.")
    parser.add_argument("--permanent", action="store_true", help="Limit to permanent roles.")
    parser.add_argument("--contract", action="store_true", help="Limit to contract roles.")
    parser.add_argument("--sort-by", help="Adzuna sort value, e.g. relevance, date, salary.")
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First page to fetch. Default: 1.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of pages to fetch. Default: 1.",
    )
    parser.add_argument(
        "--results-per-page",
        type=int,
        default=50,
        help="Requested page size. Default: 50.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.25,
        help="Delay between page requests. Default: 0.25.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path. Default: {DEFAULT_DB_PATH}.",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Do not apply pending migrations before scraping.",
    )
    return parser.parse_args()


def build_query_params(args: argparse.Namespace, app_id: str, app_key: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "app_id": app_id,
        "app_key": app_key,
        "content-type": "application/json",
        "results_per_page": args.results_per_page,
    }

    optional_params = {
        "category": args.category,
        "what": args.what,
        "where": args.where_,
        "what_exclude": args.what_exclude,
        "salary_min": args.salary_min,
        "salary_max": args.salary_max,
        "sort_by": args.sort_by,
    }
    params.update({key: value for key, value in optional_params.items() if value is not None})

    boolean_filters = {
        "full_time": args.full_time,
        "part_time": args.part_time,
        "permanent": args.permanent,
        "contract": args.contract,
    }
    params.update({key: 1 for key, enabled in boolean_filters.items() if enabled})

    return params


def params_for_storage(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in {"app_id", "app_key"}}


def fetch_page(
    client: httpx.Client,
    country: str,
    page: int,
    params: dict[str, Any],
) -> dict[str, Any]:
    response = client.get(f"{API_ROOT}/{country}/search/{page}", params=params)
    response.raise_for_status()
    return response.json()


def bool_from_provider(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value != 0)
    if isinstance(value, str):
        return int(value.strip().lower() in {"1", "true", "yes"})
    return 0


def upsert_category(connection: sqlite3.Connection, category: dict[str, Any] | None) -> str | None:
    if not category or not category.get("tag"):
        return None

    tag = str(category["tag"])
    label = str(category.get("label") or tag)
    connection.execute(
        """
        INSERT INTO categories (tag, label)
        VALUES (?, ?)
        ON CONFLICT(tag) DO UPDATE SET
            label = excluded.label,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (tag, label),
    )
    return tag


def upsert_company(connection: sqlite3.Connection, company: dict[str, Any] | None) -> int | None:
    display_name = (company or {}).get("display_name")
    if not display_name:
        return None

    connection.execute(
        """
        INSERT INTO companies (display_name)
        VALUES (?)
        ON CONFLICT(display_name) DO UPDATE SET
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (str(display_name),),
    )
    row = connection.execute(
        "SELECT id FROM companies WHERE display_name = ?",
        (str(display_name),),
    ).fetchone()
    return int(row[0])


def upsert_location(connection: sqlite3.Connection, job: dict[str, Any]) -> int | None:
    location = job.get("location") or {}
    display_name = location.get("display_name")
    if not display_name:
        return None

    area_json = json.dumps(location.get("area") or [], ensure_ascii=False, sort_keys=True)
    latitude = job.get("latitude")
    longitude = job.get("longitude")
    connection.execute(
        """
        INSERT INTO locations (display_name, area_json, latitude, longitude)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(display_name, area_json) DO UPDATE SET
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (str(display_name), area_json, latitude, longitude),
    )
    row = connection.execute(
        "SELECT id FROM locations WHERE display_name = ? AND area_json = ?",
        (str(display_name), area_json),
    ).fetchone()
    return int(row[0])


def upsert_job(connection: sqlite3.Connection, job: dict[str, Any]) -> str:
    adzuna_id = str(job["id"])
    category_tag = upsert_category(connection, job.get("category"))
    company_id = upsert_company(connection, job.get("company"))
    location_id = upsert_location(connection, job)

    connection.execute(
        """
        INSERT INTO jobs (
            adzuna_id,
            title,
            description,
            redirect_url,
            adref,
            created_at,
            salary_min,
            salary_max,
            salary_is_predicted,
            contract_type,
            contract_time,
            category_tag,
            company_id,
            location_id,
            latitude,
            longitude,
            raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(adzuna_id) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            redirect_url = excluded.redirect_url,
            adref = excluded.adref,
            created_at = excluded.created_at,
            scraped_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            salary_min = excluded.salary_min,
            salary_max = excluded.salary_max,
            salary_is_predicted = excluded.salary_is_predicted,
            contract_type = excluded.contract_type,
            contract_time = excluded.contract_time,
            category_tag = excluded.category_tag,
            company_id = excluded.company_id,
            location_id = excluded.location_id,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            raw_json = excluded.raw_json
        """,
        (
            adzuna_id,
            job.get("title") or "",
            job.get("description"),
            job.get("redirect_url"),
            job.get("adref"),
            job.get("created"),
            job.get("salary_min"),
            job.get("salary_max"),
            bool_from_provider(job.get("salary_is_predicted")),
            job.get("contract_type"),
            job.get("contract_time"),
            category_tag,
            company_id,
            location_id,
            job.get("latitude"),
            job.get("longitude"),
            json.dumps(job, ensure_ascii=False, sort_keys=True),
        ),
    )
    return adzuna_id


def create_scrape_run(
    connection: sqlite3.Connection,
    args: argparse.Namespace,
    stored_params: dict[str, Any],
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO scrape_runs (
            country,
            query_params_json,
            start_page,
            requested_results_per_page,
            status
        )
        VALUES (?, ?, ?, ?, 'running')
        """,
        (
            args.country,
            json.dumps(stored_params, ensure_ascii=False, sort_keys=True),
            args.start_page,
            args.results_per_page,
        ),
    )
    return int(cursor.lastrowid)


def mark_run_success(
    connection: sqlite3.Connection,
    run_id: int,
    end_page: int,
    total_count: int | None,
    mean_salary: float | None,
) -> None:
    connection.execute(
        """
        UPDATE scrape_runs
        SET status = 'success',
            end_page = ?,
            total_count = ?,
            mean_salary = ?,
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (end_page, total_count, mean_salary, run_id),
    )


def mark_run_failed(connection: sqlite3.Connection, run_id: int, error: Exception) -> None:
    connection.execute(
        """
        UPDATE scrape_runs
        SET status = 'failed',
            error_message = ?,
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (str(error), run_id),
    )


def scrape(args: argparse.Namespace) -> None:
    if args.pages < 1:
        raise ValueError("--pages must be at least 1")
    if args.results_per_page < 1:
        raise ValueError("--results-per-page must be at least 1")
    if not args.skip_migrations:
        apply_migrations(args.db)

    app_id, app_key = load_credentials()
    params = build_query_params(args, app_id, app_key)
    stored_params = params_for_storage(params)
    end_page = args.start_page + args.pages - 1
    total_count: int | None = None
    mean_salary: float | None = None
    inserted_links = 0

    with connect(args.db) as connection:
        run_id = create_scrape_run(connection, args, stored_params)
        connection.commit()

        try:
            with httpx.Client(timeout=30.0) as client:
                for page in range(args.start_page, end_page + 1):
                    payload = fetch_page(client, args.country, page, params)
                    total_count = payload.get("count", total_count)
                    mean_salary = payload.get("mean", mean_salary)
                    results = payload.get("results") or []

                    with connection:
                        for position, job in enumerate(results, start=1):
                            job_id = upsert_job(connection, job)
                            connection.execute(
                                """
                                INSERT OR REPLACE INTO job_scrape_runs (
                                    job_id,
                                    scrape_run_id,
                                    page_number,
                                    result_position
                                )
                                VALUES (?, ?, ?, ?)
                                """,
                                (job_id, run_id, page, position),
                            )
                            inserted_links += 1

                    print(f"Fetched page {page}: {len(results)} jobs")
                    if page < end_page:
                        time.sleep(args.delay_seconds)

            with connection:
                mark_run_success(connection, run_id, end_page, total_count, mean_salary)
        except Exception as error:
            with connection:
                mark_run_failed(connection, run_id, error)
            raise

    print(
        "Scrape complete: "
        f"run_id={run_id}, pages={args.start_page}-{end_page}, "
        f"jobs_seen={inserted_links}, provider_count={total_count}"
    )


def main() -> None:
    scrape(parse_args())


if __name__ == "__main__":
    main()
