from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pypdfium2 as pdfium
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = PROJECT_DIR.parent
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-nano-12b-v2-vl:free"
DEFAULT_MAX_PAGES = 6
DEFAULT_RENDER_SCALE = 2.0
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

CV_EXTRACTION_PROMPT = """
You are extracting data from a CV/resume PDF.

Return only valid JSON with exactly this top-level shape:
{
  "plain_text": "Full OCR text from the CV, preserving useful section headings and line breaks.",
  "structured": {
    "name": null,
    "email": null,
    "phone": null,
    "location": null,
    "summary": null,
    "skills": [],
    "experience": [
      {
        "company": null,
        "title": null,
        "location": null,
        "start_date": null,
        "end_date": null,
        "current": false,
        "description": null,
        "achievements": []
      }
    ],
    "education": [
      {
        "institution": null,
        "qualification": null,
        "field": null,
        "start_date": null,
        "end_date": null,
        "description": null
      }
    ],
    "certifications": [],
    "links": [],
    "preferred_roles": [],
    "preferred_locations": [],
    "salary_expectation": null
  }
}

Rules:
- Use null for missing scalar values.
- Use [] for missing lists.
- Do not invent data.
- Keep plain_text factual and complete.
- If the CV implies role or location preferences, include them; otherwise leave those lists empty.
""".strip()


@dataclass(frozen=True)
class RenderedPdf:
    page_count: int
    image_data_urls: list[str]


@dataclass(frozen=True)
class CvExtractionResult:
    file_sha256: str
    file_size_bytes: int
    page_count: int
    model: str
    plain_text: str
    structured: dict[str, Any]
    provider_response: dict[str, Any]
    openrouter_duration_seconds: float


def load_openrouter_settings() -> tuple[str, str, int, float]:
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

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    max_pages = int(os.getenv("CV_OCR_MAX_PAGES", str(DEFAULT_MAX_PAGES)))
    render_scale = float(os.getenv("CV_OCR_RENDER_SCALE", str(DEFAULT_RENDER_SCALE)))
    return api_key, model, max_pages, render_scale


def render_pdf_pages(pdf_bytes: bytes, *, max_pages: int, scale: float) -> RenderedPdf:
    try:
        document = pdfium.PdfDocument(pdf_bytes)
    except Exception as error:
        raise ValueError("Uploaded file is not a readable PDF") from error

    page_count = len(document)
    if page_count == 0:
        raise ValueError("Uploaded PDF contains no pages")

    image_data_urls: list[str] = []
    for page_index in range(min(page_count, max_pages)):
        page = document[page_index]
        bitmap = page.render(scale=scale).to_pil()
        image_buffer = io.BytesIO()
        bitmap.save(image_buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
        image_data_urls.append(f"data:image/png;base64,{encoded}")
        page.close()

    document.close()
    return RenderedPdf(page_count=page_count, image_data_urls=image_data_urls)


def build_openrouter_payload(model: str, image_data_urls: list[str]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": CV_EXTRACTION_PROMPT}]
    content.extend(
        {"type": "image_url", "image_url": {"url": image_data_url}}
        for image_data_url in image_data_urls
    )

    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 6000,
        "response_format": {"type": "json_object"},
    }


def openrouter_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://127.0.0.1:8000",
        "X-Title": "Jobs Data CV Extractor",
    }


def request_openrouter(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers = openrouter_headers(api_key)
    with httpx.Client(timeout=120.0) as client:
        response = client.post(OPENROUTER_URL, headers=headers, json=payload)
        if response.status_code in {400, 422} and "response_format" in payload:
            fallback_payload = {
                key: value for key, value in payload.items() if key != "response_format"
            }
            response = client.post(OPENROUTER_URL, headers=headers, json=fallback_payload)
        response.raise_for_status()
        return response.json()


def assistant_content(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices") or []
    if not choices:
        raise ValueError("OpenRouter response did not include choices")

    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "\n".join(part for part in text_parts if part)
    raise ValueError("OpenRouter response did not include text content")


def parse_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    fence_match = JSON_FENCE_RE.fullmatch(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise ValueError("Model response was not valid JSON") from error

    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON was not an object")
    return parsed


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return str(value)


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def normalize_extraction(parsed: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    plain_text = parsed.get("plain_text")
    structured = parsed.get("structured")

    if not isinstance(plain_text, str):
        raise ValueError("Model response missing string plain_text")
    if not isinstance(structured, dict):
        raise ValueError("Model response missing object structured")

    normalized: dict[str, Any] = {
        "name": string_or_none(structured.get("name")),
        "email": string_or_none(structured.get("email")),
        "phone": string_or_none(structured.get("phone")),
        "location": string_or_none(structured.get("location")),
        "summary": string_or_none(structured.get("summary")),
        "skills": string_list(structured.get("skills")),
        "experience": dict_list(structured.get("experience")),
        "education": dict_list(structured.get("education")),
        "certifications": string_list(structured.get("certifications")),
        "links": string_list(structured.get("links")),
        "preferred_roles": string_list(structured.get("preferred_roles")),
        "preferred_locations": string_list(structured.get("preferred_locations")),
        "salary_expectation": string_or_none(structured.get("salary_expectation")),
    }
    return plain_text.strip(), normalized


def extract_cv_from_pdf(pdf_bytes: bytes) -> CvExtractionResult:
    api_key, model, max_pages, render_scale = load_openrouter_settings()
    rendered = render_pdf_pages(pdf_bytes, max_pages=max_pages, scale=render_scale)
    payload = build_openrouter_payload(model, rendered.image_data_urls)
    openrouter_started_at = time.perf_counter()
    response_payload = request_openrouter(api_key, payload)
    openrouter_duration_seconds = time.perf_counter() - openrouter_started_at
    content = assistant_content(response_payload)
    parsed = parse_json_content(content)
    plain_text, structured = normalize_extraction(parsed)

    provider_response = {
        "id": response_payload.get("id"),
        "model": response_payload.get("model"),
        "usage": response_payload.get("usage"),
        "finish_reason": (response_payload.get("choices") or [{}])[0].get("finish_reason"),
        "openrouter_duration_seconds": round(openrouter_duration_seconds, 3),
        "assistant_content": content,
    }

    return CvExtractionResult(
        file_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        file_size_bytes=len(pdf_bytes),
        page_count=rendered.page_count,
        model=model,
        plain_text=plain_text,
        structured=structured,
        provider_response=provider_response,
        openrouter_duration_seconds=openrouter_duration_seconds,
    )
