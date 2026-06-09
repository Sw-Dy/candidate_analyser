from __future__ import annotations

import csv
import io
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import (
    BASE_DIR,
    DATABASE_PATH,
    LIVE_ANALYSIS_JSON_PATH,
    LIVE_API_CORPUS_JSON_PATH,
)
from app.database import fetch_latest_snapshot, initialize_database, save_snapshot
from app.services.aggregate_dashboard import build_aggregate_dashboard
from app.services.analytics import build_all_candidate_analysis
from app.services.api_client import LMSApiClient

logger = logging.getLogger("student_dashboard")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database(DATABASE_PATH)
    yield


app = FastAPI(
    title="Student Assessment Analytics Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Student Assessment Analytics Dashboard"},
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard/analytics")
async def dashboard_analytics(
    force_refresh: bool = Query(default=True),
    candidate_id: int | None = Query(default=None),
    exam_id: int | None = Query(default=None),
) -> JSONResponse:
    payload, source = await _load_dashboard_payload(
        force_refresh=force_refresh,
        candidate_id=candidate_id,
        exam_id=exam_id,
    )
    return JSONResponse(content={"data": payload, "source": source})


@app.get("/api/dashboard/overview")
async def dashboard_overview(
    force_refresh: bool = Query(default=True),
    selected_candidate_id: int | None = Query(default=None),
    candidate_id: int | None = Query(default=None),
    exam_id: int | None = Query(default=None),
) -> JSONResponse:
    analysis_payload, source = await _load_dashboard_payload(
        force_refresh=force_refresh,
        candidate_id=candidate_id,
        exam_id=exam_id,
    )
    effective_candidate_id = candidate_id if candidate_id is not None else selected_candidate_id
    if effective_candidate_id is not None and not _payload_has_candidate(analysis_payload, effective_candidate_id):
        file_payload = _load_live_analysis_payload()
        if (
            candidate_id is None
            and exam_id is None
            and file_payload is not None
            and _payload_has_candidate(file_payload, effective_candidate_id)
        ):
            analysis_payload = file_payload
            source = "file"
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No cached analysis found for candidate_id {effective_candidate_id}. "
                "Call /api/analysis/all?force_refresh=true to rebuild the analysis.",
            )

    corpus_payload = _load_live_corpus_payload()
    overview = build_aggregate_dashboard(
        analysis_payload,
        corpus_payload,
        source=source,
        selected_candidate_id=effective_candidate_id,
        selected_exam_id=exam_id,
    )
    return JSONResponse(content=overview)


@app.get("/api/analysis/all")
async def analysis_all(
    force_refresh: bool = Query(default=True),
    candidate_id: int | None = Query(default=None),
    exam_id: int | None = Query(default=None),
) -> JSONResponse:
    payload, _ = await _load_dashboard_payload(
        force_refresh=force_refresh,
        candidate_id=candidate_id,
        exam_id=exam_id,
    )
    return JSONResponse(content=payload)


@app.get("/api/analysis/latest")
async def analysis_latest() -> JSONResponse:
    cached_payload = fetch_latest_snapshot(DATABASE_PATH)
    if cached_payload is None:
        raise HTTPException(
            status_code=404,
            detail="No cached analysis is available yet. Call /api/analysis/all first.",
        )
    return JSONResponse(content=cached_payload)


@app.get("/api/analysis/candidate/{candidate_id}")
async def analysis_candidate(
    candidate_id: int,
    force_refresh: bool = Query(default=False),
    exam_id: int | None = Query(default=None),
) -> JSONResponse:
    payload, _ = await _load_dashboard_payload(
        force_refresh=force_refresh,
        candidate_id=candidate_id,
        exam_id=exam_id,
    )
    candidate_payload = _extract_candidate_analysis(payload, candidate_id, exam_id)
    if candidate_payload is None:
        detail = f"No analysis found for candidate_id {candidate_id}."
        if exam_id is not None:
            detail = f"No analysis found for candidate_id {candidate_id} and exam_id {exam_id}."
        raise HTTPException(status_code=404, detail=detail)
    return JSONResponse(content=candidate_payload)


@app.get("/api/analysis/candidate/{candidate_id}/attempts")
async def analysis_candidate_attempts(
    candidate_id: int,
    force_refresh: bool = Query(default=False),
    exam_id: int | None = Query(default=None),
) -> JSONResponse:
    payload, _ = await _load_dashboard_payload(
        force_refresh=force_refresh,
        candidate_id=candidate_id,
        exam_id=exam_id,
    )
    candidate_payload = _extract_candidate_analysis(payload, candidate_id, exam_id)
    if candidate_payload is None:
        detail = f"No attempts found for candidate_id {candidate_id}."
        if exam_id is not None:
            detail = f"No attempts found for candidate_id {candidate_id} and exam_id {exam_id}."
        raise HTTPException(status_code=404, detail=detail)
    return JSONResponse(content={"candidate_id": candidate_id, "attempts": candidate_payload.get("attempts", [])})


async def _load_dashboard_payload(
    force_refresh: bool,
    *,
    candidate_id: int | None = None,
    exam_id: int | None = None,
) -> tuple[dict, str]:
    use_shared_cache = candidate_id is None and exam_id is None
    if use_shared_cache and not force_refresh:
        cached_payload = fetch_latest_snapshot(DATABASE_PATH)
        if cached_payload is not None:
            return cached_payload, "cache"

    try:
        payload = await _build_and_store_dashboard_payload(candidate_id=candidate_id, exam_id=exam_id)
        if use_shared_cache and _is_empty_candidate_payload(payload):
            cached_payload = fetch_latest_snapshot(DATABASE_PATH)
            if cached_payload is not None and not _is_empty_candidate_payload(cached_payload):
                logger.warning("Live dashboard refresh returned no candidates; using cached snapshot")
                return cached_payload, "cache"
        return payload, "live"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Dashboard analytics build failed")
        cached_payload = fetch_latest_snapshot(DATABASE_PATH)
        if use_shared_cache and cached_payload is not None:
            return cached_payload, "cache"
        raise HTTPException(status_code=502, detail=f"Unable to build dashboard analytics: {exc}") from exc


def _is_empty_candidate_payload(payload: dict) -> bool:
    if payload.get("analysis_scope") == "multi_candidate":
        return int(payload.get("candidate_count") or 0) == 0
    if "overview" in payload:
        return int(payload.get("overview", {}).get("total_candidates") or 0) == 0
    return not payload.get("student") and not payload.get("candidate_analyses")


async def _build_and_store_dashboard_payload(
    *,
    candidate_id: int | None = None,
    exam_id: int | None = None,
) -> dict:
    client = LMSApiClient()
    raw_payload = await client.fetch_all(candidate_id=candidate_id, exam_id=exam_id)
    logger.info("Upstream API payloads:\n%s", json.dumps(raw_payload.get("raw_apis", {}), indent=2, default=str))
    payload = await build_all_candidate_analysis(raw_payload)
    logger.info("Computed analytics snapshot:\n%s", json.dumps(payload, indent=2, default=str))
    if candidate_id is None and exam_id is None:
        _write_live_json_files(raw_payload=raw_payload, payload=payload)
        payload["snapshot_id"] = save_snapshot(DATABASE_PATH, payload)
    return payload


def _write_live_json_files(*, raw_payload: dict, payload: dict) -> None:
    corpus_payload = {
        "generated_at": payload.get("generated_at"),
        "analysis_scope": payload.get("analysis_scope", "single_candidate"),
        "candidate_count": payload.get("candidate_count", 0),
        "attempt_count": payload.get("attempt_count", 0),
        "candidates": payload.get("candidates", []),
        "apis": {
            "course_list": {
                "items": raw_payload.get("course_list", []),
                "count": len(raw_payload.get("course_list", [])),
                "raw_api": raw_payload.get("raw_apis", {}).get("course_list", {}),
            },
            "all_candidate_attempts": {
                "items": raw_payload.get("all_candidate_attempts", []),
                "count": len(raw_payload.get("all_candidate_attempts", [])),
                "raw_api": raw_payload.get("raw_apis", {}).get("all_candidate_attempts", {}),
            },
            "candidate_profile": {
                "data": raw_payload.get("candidate_profile", {}),
                "raw_api": raw_payload.get("raw_apis", {}).get("candidate_profile", {}),
            },
            "candidate_details": {
                "data": raw_payload.get("candidate", {}),
                "raw_api": raw_payload.get("raw_apis", {}).get("candidate_details", {}),
            },
            "candidate_records": {
                "items": raw_payload.get("candidate_records", {}),
                "count": len(raw_payload.get("candidate_records", {})),
            },
        },
    }

    LIVE_API_CORPUS_JSON_PATH.write_text(
        json.dumps(corpus_payload, indent=2, default=str),
        encoding="utf-8",
    )
    LIVE_ANALYSIS_JSON_PATH.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )


def _load_live_corpus_payload() -> dict:
    if LIVE_API_CORPUS_JSON_PATH.exists():
        return json.loads(LIVE_API_CORPUS_JSON_PATH.read_text(encoding="utf-8"))
    return {}


def _load_live_analysis_payload() -> dict | None:
    if LIVE_ANALYSIS_JSON_PATH.exists():
        return json.loads(LIVE_ANALYSIS_JSON_PATH.read_text(encoding="utf-8"))
    return None


def _payload_has_candidate(payload: dict, candidate_id: int) -> bool:
    if payload.get("candidate_analyses"):
        return str(candidate_id) in payload.get("candidate_analyses", {})
    if int(payload.get("student", {}).get("candidate_id") or 0) == candidate_id:
        return True
    return any(
        int(row.get("candidate_id") or 0) == candidate_id
        for row in payload.get("ranked_candidates", payload.get("rankings", []))
    )


def _extract_candidate_analysis(payload: dict, candidate_id: int, exam_id: int | None = None) -> dict | None:
    if payload.get("candidate_analyses"):
        candidate_payload = payload.get("candidate_analyses", {}).get(str(candidate_id))
        if candidate_payload is None:
            return None
        return _filter_candidate_analysis_by_exam(candidate_payload, exam_id)
    if int(payload.get("student", {}).get("candidate_id") or 0) == candidate_id:
        if exam_id is not None and int(payload.get("exam", {}).get("exam_id") or 0) != exam_id:
            return None
        return {
            "candidate_id": candidate_id,
            "candidate_name": payload.get("student", {}).get("name"),
            "profile": payload.get("student", {}),
            "primary_attempt": payload,
            "attempts": [payload],
        }
    return None


def _filter_candidate_analysis_by_exam(candidate_payload: dict, exam_id: int | None) -> dict | None:
    if exam_id is None:
        return candidate_payload

    attempts = [
        attempt
        for attempt in candidate_payload.get("attempts", [])
        if int(attempt.get("exam", {}).get("exam_id") or 0) == exam_id
    ]
    if not attempts:
        return None

    attempt_summaries = [
        summary
        for summary in candidate_payload.get("attempt_summaries", [])
        if int(summary.get("exam_id") or 0) == exam_id
    ]
    primary_attempt = max(
        attempts,
        key=lambda item: (
            float(item.get("summary", {}).get("overall_score_percent") or 0),
            float(item.get("summary", {}).get("accuracy") or 0),
        ),
    )
    return {
        **candidate_payload,
        "attempts": attempts,
        "attempt_summaries": attempt_summaries,
        "primary_attempt": primary_attempt,
        "summary": {
            **candidate_payload.get("summary", {}),
            "attempts": len(attempts),
            "best_exam": primary_attempt.get("exam", {}).get("name"),
            "best_marks_percent": primary_attempt.get("summary", {}).get("overall_score_percent", 0),
            "average_accuracy": round(
                sum(float(item.get("summary", {}).get("accuracy") or 0) for item in attempts) / len(attempts),
                2,
            ),
            "average_marks_percent": round(
                sum(float(item.get("summary", {}).get("overall_score_percent") or 0) for item in attempts)
                / len(attempts),
                2,
            ),
        },
    }


@app.get("/api/analysis/corpus/latest")
async def analysis_corpus_latest(force_refresh: bool = Query(default=False)) -> JSONResponse:
    if force_refresh:
        await _build_and_store_dashboard_payload()

    if not LIVE_API_CORPUS_JSON_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="No live corpus JSON is available yet. Call /api/analysis/all first.",
        )

    return JSONResponse(content=json.loads(LIVE_API_CORPUS_JSON_PATH.read_text(encoding="utf-8")))


@app.get("/api/dashboard/history")
async def dashboard_history() -> JSONResponse:
    cached_payload = fetch_latest_snapshot(DATABASE_PATH)
    if cached_payload is None:
        return JSONResponse(content={"items": []})

    exam = cached_payload["exam"]
    student = cached_payload["student"]
    summary = cached_payload["summary"]
    item = {
        "snapshot_id": cached_payload.get("snapshot_id"),
        "generated_at": cached_payload["generated_at"],
        "candidate_id": student["candidate_id"],
        "student_name": student["name"],
        "exam_name": exam["name"],
        "accuracy": summary["accuracy"],
        "score_percent": summary["overall_score_percent"],
    }
    return JSONResponse(content={"items": [item]})


@app.get("/api/dashboard/export/csv")
async def export_csv() -> StreamingResponse:
    cached_payload = fetch_latest_snapshot(DATABASE_PATH)
    if cached_payload is None:
        client = LMSApiClient()
        raw_payload = await client.fetch_all()
        cached_payload = await build_all_candidate_analysis(raw_payload)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Question ID",
            "Question",
            "Domain",
            "Primary Skill",
            "Topic",
            "Difficulty",
            "Difficulty Rating",
            "Status",
            "Marks Obtained",
            "Full Marks",
            "Time Spent (s)",
        ]
    )
    question_rows = []
    if cached_payload.get("analysis_scope") == "multi_candidate":
        for candidate in cached_payload.get("candidates", []):
            for attempt in candidate.get("attempts", []):
                for question in attempt.get("questions", []):
                    question_rows.append(
                        {
                            **question,
                            "candidate_id": candidate.get("candidate_id"),
                            "candidate_name": candidate.get("candidate_name"),
                            "exam_name": attempt.get("exam", {}).get("name"),
                        }
                    )
    else:
        question_rows = cached_payload.get("questions", [])

    for question in question_rows:
        writer.writerow(
            [
                question["question_id"],
                question["question_text"],
                question["domain"],
                question.get("primary_skill", ""),
                question["topic"],
                question.get("difficulty_label", question["difficulty"]),
                question.get("difficulty_rating", ""),
                question["status"],
                question["marks_obtained"],
                question["full_marks"],
                question["time_spent_seconds"],
            ]
        )

    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="student-assessment-analytics.csv"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)
