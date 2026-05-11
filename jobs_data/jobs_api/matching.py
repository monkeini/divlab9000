from __future__ import annotations

import hashlib
import json
import pickle
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from jobs_api.database import PROJECT_DIR
from jobs_api.models import CvDocument, CvPreferences
from jobs_api.tokenizer import tokenize

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
INDEX_DIR = PROJECT_DIR / "indexes"
TOKEN_INDEX_PATH = INDEX_DIR / "bm25_tokens.pkl"
DENSE_INDEX_PATH = INDEX_DIR / "dense_embeddings.npy"
METADATA_PATH = INDEX_DIR / "metadata.json"


@dataclass(frozen=True)
class CorpusJob:
    adzuna_id: str
    title: str
    description: str | None
    category_tag: str | None
    category_label: str | None
    company: str | None
    location: str | None
    salary_min: float | None
    salary_max: float | None
    updated_at: str | None
    scraped_at: str | None


@dataclass(frozen=True)
class IndexBuildResult:
    built: bool
    fingerprint: str
    model_name: str
    job_count: int
    metadata_path: Path


@dataclass(frozen=True)
class RetrievalCandidate:
    job_id: str
    rank: int
    bm25_rank: int | None
    dense_rank: int | None
    rrf_score: float
    bm25_score: float
    dense_score: float
    preference_filters: dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def corpus_rows(connection: sqlite3.Connection) -> list[CorpusJob]:
    rows = connection.execute(
        """
        SELECT
            j.adzuna_id,
            j.title,
            j.description,
            j.category_tag,
            c.label AS category_label,
            co.display_name AS company_display_name,
            l.display_name AS location_display_name,
            j.salary_min,
            j.salary_max,
            j.updated_at,
            j.scraped_at
        FROM jobs j
        LEFT JOIN categories c ON c.tag = j.category_tag
        LEFT JOIN companies co ON co.id = j.company_id
        LEFT JOIN locations l ON l.id = j.location_id
        ORDER BY j.adzuna_id
        """
    ).fetchall()
    return [
        CorpusJob(
            adzuna_id=row["adzuna_id"],
            title=row["title"],
            description=row["description"],
            category_tag=row["category_tag"],
            category_label=row["category_label"],
            company=row["company_display_name"],
            location=row["location_display_name"],
            salary_min=row["salary_min"],
            salary_max=row["salary_max"],
            updated_at=row["updated_at"],
            scraped_at=row["scraped_at"],
        )
        for row in rows
    ]


def job_text(job: CorpusJob) -> str:
    return "\n".join(
        part
        for part in [
            job.title,
            job.description,
            job.category_tag,
            job.category_label,
            job.company,
            job.location,
        ]
        if part
    )


def corpus_fingerprint(jobs: list[CorpusJob]) -> str:
    digest = hashlib.sha256()
    for job in jobs:
        stable_payload = {
            "adzuna_id": job.adzuna_id,
            "title": job.title,
            "description": job.description,
            "category_tag": job.category_tag,
            "company": job.company,
            "location": job.location,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "updated_at": job.updated_at,
            "scraped_at": job.scraped_at,
        }
        digest.update(json.dumps(stable_payload, sort_keys=True, ensure_ascii=False).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def read_metadata() -> dict[str, Any] | None:
    if not METADATA_PATH.exists():
        return None
    try:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def indexes_are_current(
    *,
    fingerprint: str,
    model_name: str,
    job_count: int,
) -> bool:
    metadata = read_metadata()
    if not metadata:
        return False
    return (
        metadata.get("corpus_fingerprint") == fingerprint
        and metadata.get("model_name") == model_name
        and metadata.get("job_count") == job_count
        and TOKEN_INDEX_PATH.exists()
        and DENSE_INDEX_PATH.exists()
    )


@lru_cache(maxsize=2)
def get_embedding_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


def encode_texts(
    model_name: str,
    texts: list[str],
    *,
    show_progress: bool = False,
) -> np.ndarray:
    model = get_embedding_model(model_name)
    embeddings = model.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=show_progress,
    )
    return np.asarray(embeddings, dtype=np.float32)


def ensure_indexes(
    connection: sqlite3.Connection,
    *,
    force: bool = False,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> IndexBuildResult:
    jobs = corpus_rows(connection)
    fingerprint = corpus_fingerprint(jobs)
    if not force and indexes_are_current(
        fingerprint=fingerprint,
        model_name=model_name,
        job_count=len(jobs),
    ):
        return IndexBuildResult(
            built=False,
            fingerprint=fingerprint,
            model_name=model_name,
            job_count=len(jobs),
            metadata_path=METADATA_PATH,
        )

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    job_ids = [job.adzuna_id for job in jobs]
    texts = [job_text(job) for job in jobs]
    token_corpus = [tokenize(text) for text in texts]
    dense_embeddings = (
        encode_texts(model_name, texts, show_progress=True)
        if texts
        else np.empty((0, 0), np.float32)
    )

    with TOKEN_INDEX_PATH.open("wb") as handle:
        pickle.dump({"job_ids": job_ids, "token_corpus": token_corpus}, handle)
    np.save(DENSE_INDEX_PATH, dense_embeddings)
    METADATA_PATH.write_text(
        json.dumps(
            {
                "corpus_fingerprint": fingerprint,
                "model_name": model_name,
                "job_count": len(jobs),
                "built_at": utc_now_iso(),
                "bm25_tokens_path": str(TOKEN_INDEX_PATH.name),
                "dense_embeddings_path": str(DENSE_INDEX_PATH.name),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return IndexBuildResult(
        built=True,
        fingerprint=fingerprint,
        model_name=model_name,
        job_count=len(jobs),
        metadata_path=METADATA_PATH,
    )


def load_token_index() -> tuple[list[str], list[list[str]]]:
    with TOKEN_INDEX_PATH.open("rb") as handle:
        payload = pickle.load(handle)
    return payload["job_ids"], payload["token_corpus"]


def structured_cv_text(cv: CvDocument) -> str:
    structured = cv.structured
    parts: list[str] = [
        cv.plain_text,
        structured.summary or "",
        " ".join(structured.skills),
        " ".join(structured.preferred_roles),
        " ".join(structured.preferred_locations),
        structured.salary_expectation or "",
    ]
    for item in structured.experience:
        parts.extend(
            str(item.get(key, ""))
            for key in ("title", "company", "description", "location")
            if item.get(key)
        )
    return "\n".join(part for part in parts if part)


def preference_query_text(preferences: CvPreferences) -> str:
    parts: list[str] = []
    if preferences.preferred_location:
        parts.append(preferences.preferred_location)
    if preferences.industry_keyword:
        parts.append(preferences.industry_keyword)
    if preferences.working_arrangements:
        parts.extend(
            arrangement.replace("_", " ") for arrangement in preferences.working_arrangements
        )
    return "\n".join(parts)


def retrieval_query_text(cv: CvDocument) -> str:
    return "\n".join(
        part
        for part in [
            structured_cv_text(cv),
            preference_query_text(cv.preferences),
        ]
        if part
    )


def salary_filter_passes(job: CorpusJob, preferences: CvPreferences) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if preferences.salary_min is not None and job.salary_max is not None:
        if job.salary_max < preferences.salary_min:
            return False, ["salary_max_below_candidate_min"]
    if preferences.salary_max is not None and job.salary_min is not None:
        if job.salary_min > preferences.salary_max:
            return False, ["salary_min_above_candidate_max"]
    return True, reasons


def location_boost(job: CorpusJob, preferences: CvPreferences) -> float:
    if not preferences.preferred_location or not job.location:
        return 0.0
    preferred_tokens = set(tokenize(preferences.preferred_location))
    location_tokens = set(tokenize(job.location))
    if not preferred_tokens or not location_tokens:
        return 0.0
    overlap = preferred_tokens & location_tokens
    if not overlap:
        return 0.0
    return min(0.04, 0.015 * len(overlap))


def rank_lookup(scores: np.ndarray) -> dict[int, int]:
    ranked = np.argsort(-scores, kind="mergesort")
    return {int(index): rank + 1 for rank, index in enumerate(ranked)}


def retrieve_candidates(
    connection: sqlite3.Connection,
    *,
    cv: CvDocument,
    retrieve_k: int = 50,
    rrf_k: int = 60,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> tuple[list[RetrievalCandidate], dict[str, Any]]:
    index_result = ensure_indexes(connection, model_name=model_name)
    jobs = corpus_rows(connection)
    jobs_by_id = {job.adzuna_id: job for job in jobs}
    job_ids, token_corpus = load_token_index()
    dense_embeddings = np.load(DENSE_INDEX_PATH)

    query_text = retrieval_query_text(cv)
    bm25 = BM25Okapi(token_corpus)
    bm25_scores = np.asarray(bm25.get_scores(tokenize(query_text)), dtype=np.float64)

    if dense_embeddings.size:
        query_embedding = encode_texts(model_name, [query_text])[0]
        dense_scores = np.asarray(dense_embeddings @ query_embedding, dtype=np.float64)
    else:
        dense_scores = np.zeros(len(job_ids), dtype=np.float64)

    bm25_ranks = rank_lookup(bm25_scores)
    dense_ranks = rank_lookup(dense_scores)

    candidates: list[RetrievalCandidate] = []
    for index, job_id in enumerate(job_ids):
        job = jobs_by_id[job_id]
        passes_salary, filter_reasons = salary_filter_passes(job, cv.preferences)
        if not passes_salary:
            continue

        bm25_rank = bm25_ranks.get(index)
        dense_rank = dense_ranks.get(index)
        score = 0.0
        if bm25_rank is not None:
            score += 1.0 / (rrf_k + bm25_rank)
        if dense_rank is not None:
            score += 1.0 / (rrf_k + dense_rank)
        boost = location_boost(job, cv.preferences)
        score += boost

        candidates.append(
            RetrievalCandidate(
                job_id=job_id,
                rank=0,
                bm25_rank=bm25_rank,
                dense_rank=dense_rank,
                rrf_score=score,
                bm25_score=float(bm25_scores[index]),
                dense_score=float(dense_scores[index]),
                preference_filters={
                    "preferred_location": cv.preferences.preferred_location,
                    "salary_min": cv.preferences.salary_min,
                    "salary_max": cv.preferences.salary_max,
                    "working_arrangements": cv.preferences.working_arrangements,
                    "industry_keyword": cv.preferences.industry_keyword,
                    "salary_filter_reasons": filter_reasons,
                    "location_boost": boost,
                },
            )
        )

    candidates.sort(key=lambda item: (-item.rrf_score, item.bm25_rank or 10**9, item.job_id))
    ranked_candidates = [
        RetrievalCandidate(
            job_id=item.job_id,
            rank=rank,
            bm25_rank=item.bm25_rank,
            dense_rank=item.dense_rank,
            rrf_score=item.rrf_score,
            bm25_score=item.bm25_score,
            dense_score=item.dense_score,
            preference_filters=item.preference_filters,
        )
        for rank, item in enumerate(candidates[:retrieve_k], start=1)
    ]
    metadata = {
        "index_fingerprint": index_result.fingerprint,
        "index_model": index_result.model_name,
        "index_built": index_result.built,
        "job_count": index_result.job_count,
    }
    return ranked_candidates, metadata
