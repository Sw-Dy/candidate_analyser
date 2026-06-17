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
    LIVE_ANALYSIS_JSON_PATH,
    LIVE_API_CORPUS_JSON_PATH,
)
from app.services.aggregate_dashboard import build_aggregate_dashboard
from app.services.analytics import build_all_candidate_analysis
from app.services.api_client import LMSApiClient

logger = logging.getLogger("student_dashboard")


@asynccontextmanager
async def lifespan(_: FastAPI):
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
        raise HTTPException(
            status_code=404,
            detail=f"No live analysis found for candidate_id {effective_candidate_id}.",
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
    payload, _ = await _load_dashboard_payload(force_refresh=True)
    return JSONResponse(content=payload)


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


@app.get("/api/analysis/candidate/{candidate_id}/exam/{exam_id}")
async def analysis_candidate_exam(
    candidate_id: int,
    exam_id: int,
    force_refresh: bool = Query(default=False),
) -> JSONResponse:
    payload, source = await _load_dashboard_payload(
        force_refresh=force_refresh,
        candidate_id=candidate_id,
        exam_id=exam_id,
    )
    candidate_payload = _extract_candidate_analysis(payload, candidate_id, exam_id)
    if candidate_payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analysis found for candidate_id {candidate_id} and exam_id {exam_id}.",
        )
    return JSONResponse(
        content=_build_candidate_exam_analysis_response(
            analysis_payload=payload,
            candidate_payload=candidate_payload,
            candidate_id=candidate_id,
            exam_id=exam_id,
            generated_at=payload.get("generated_at"),
            source=source,
        )
    )


async def _load_dashboard_payload(
    force_refresh: bool,
    *,
    candidate_id: int | None = None,
    exam_id: int | None = None,
) -> tuple[dict, str]:
    try:
        payload = await _build_and_store_dashboard_payload(candidate_id=candidate_id, exam_id=exam_id)
        if _is_empty_candidate_payload(payload):
            logger.warning("Live dashboard refresh returned no candidates")
        return payload, "live"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Dashboard analytics build failed")
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
    logger.info("Computed live analytics:\n%s", json.dumps(payload, indent=2, default=str))
    _write_live_json_files(raw_payload=raw_payload, payload=payload)
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


def _build_candidate_exam_analysis_response(
    *,
    analysis_payload: dict,
    candidate_payload: dict,
    candidate_id: int,
    exam_id: int,
    generated_at: str | None,
    source: str,
) -> dict:
    attempts = candidate_payload.get("attempts", [])
    primary_attempt = candidate_payload.get("primary_attempt", {}) or (attempts[0] if attempts else {})
    compact_analyses = [_build_compact_attempt_analysis(attempt) for attempt in attempts]
    profile = candidate_payload.get("profile", {})
    candidate_name = candidate_payload.get("candidate_name") or profile.get("name") or f"Candidate {candidate_id}"
    return {
        "generated_at": generated_at,
        "source": source,
        "candidate": _build_candidate_basics(candidate_id, candidate_name, profile),
        "exam": primary_attempt.get("exam") or {"exam_id": exam_id, "name": f"Exam {exam_id}"},
        "summary": candidate_payload.get("summary", {}),
        "attempt_summaries": candidate_payload.get("attempt_summaries", []),
        "questions": _build_question_rows(attempts),
        "analysis_count": len(attempts),
        "primary_attempt_id": primary_attempt.get("attempt_id"),
        "analyses": compact_analyses,
        "top_performer_analysis": _build_top_performer_analysis_for_exam(analysis_payload, exam_id),
    }


def _build_candidate_basics(candidate_id: int, candidate_name: str, profile: dict) -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "registration_number": profile.get("registration_number", "Unavailable"),
        "mobile": profile.get("mobile", "N/A"),
        "gender": profile.get("gender", "N/A"),
        "course": profile.get("course", "Not provided"),
        "batch": profile.get("batch", "Not provided"),
        "applied_position": profile.get("applied_position", "Not provided"),
        "languages": profile.get("languages", []),
        "computer_proficiency": profile.get("computer_proficiency", ""),
    }


def _build_compact_attempt_analysis(attempt: dict) -> dict:
    return {
        "attempt_id": attempt.get("attempt_id"),
        "attempt_source": attempt.get("attempt_source"),
        "summary": attempt.get("summary", {}),
        "domains": _clean_domain_rows(attempt.get("domains", [])),
        "strengths": attempt.get("strengths", []),
        "weaknesses": attempt.get("weaknesses", []),
        "skill_radar": attempt.get("skill_radar", {}),
        "ranking_summary": attempt.get("ranking_summary", {}),
        "recommendations": attempt.get("recommendations", []),
        "recommended_courses": attempt.get("recommended_courses", []),
        "generated_at": attempt.get("generated_at"),
    }


def _build_question_rows(attempts: list[dict]) -> list[dict]:
    question_rows = []
    for attempt in attempts:
        attempt_id = attempt.get("attempt_id")
        for question in attempt.get("questions", []):
            question_rows.append(
                {
                    "attempt_id": attempt_id,
                    "question_id": question.get("question_id"),
                    "question_text": question.get("question_text"),
                    "question_type": question.get("question_type"),
                    "domain": _clean_ai_label(question.get("domain")),
                    "topic": _clean_ai_label(question.get("topic")),
                    "primary_skill": _clean_ai_label(question.get("primary_skill")),
                    "supporting_skills": question.get("supporting_skills", []),
                    "mapping_source": question.get("mapping_source"),
                    "label_quality": question.get("label_quality"),
                    "label_warnings": question.get("label_warnings", []),
                    "difficulty_label": question.get("difficulty_label", question.get("difficulty")),
                    "difficulty_rating": question.get("difficulty_rating"),
                    "status": question.get("status"),
                    "is_answered": question.get("is_answered"),
                    "is_correct": question.get("is_correct"),
                    "marks_obtained": question.get("marks_obtained"),
                    "full_marks": question.get("full_marks"),
                    "marks_percent": question.get("marks_percent"),
                    "negative_marks": question.get("negative_marks"),
                    "time_spent_seconds": question.get("time_spent_seconds"),
                    "selected_answer": question.get("selected_answer"),
                    "correct_answer": question.get("correct_answer"),
                }
            )
    return question_rows


def _build_top_performer_analysis_for_exam(analysis_payload: dict, exam_id: int) -> dict:
    top_performer = analysis_payload.get("top_performer", {}) or {}
    top_candidate_id = int(top_performer.get("candidate_id") or 0)
    if not top_candidate_id:
        return {}

    top_candidate_payload = analysis_payload.get("candidate_analyses", {}).get(str(top_candidate_id))
    if top_candidate_payload:
        filtered_payload = _filter_candidate_analysis_by_exam(top_candidate_payload, exam_id)
        if filtered_payload is None:
            return {"ranking": top_performer}
        primary_attempt = filtered_payload.get("primary_attempt", {}) or {}
        profile = filtered_payload.get("profile", {})
        candidate_name = filtered_payload.get("candidate_name") or profile.get("name") or f"Candidate {top_candidate_id}"
        return {
            "candidate": _build_candidate_basics(top_candidate_id, candidate_name, profile),
            "ranking": top_performer,
            "summary": filtered_payload.get("summary", {}),
            "attempt_summaries": filtered_payload.get("attempt_summaries", []),
            "questions": _build_question_rows(filtered_payload.get("attempts", [])),
            "domains": _clean_domain_rows(primary_attempt.get("domains", [])),
            "strengths": primary_attempt.get("strengths", []),
            "weaknesses": primary_attempt.get("weaknesses", []),
            "skill_radar": primary_attempt.get("skill_radar", {}),
            "recommendations": primary_attempt.get("recommendations", []),
            "recommended_courses": primary_attempt.get("recommended_courses", []),
            "primary_attempt_id": primary_attempt.get("attempt_id"),
        }

    return {"ranking": top_performer}


def _clean_domain_rows(domains: list[dict]) -> list[dict]:
    cleaned = []
    for domain in domains:
        domain_name = _clean_ai_label(domain.get("domain"))
        if domain_name is None:
            continue
        cleaned.append({**domain, "domain": domain_name})
    return cleaned


def _clean_ai_label(value: object) -> str | None:
    label = str(value or "").strip()
    if not label or label.lower() == "pending ai label":
        return None
    return label


@app.get("/api/analysis/corpus/latest")
async def analysis_corpus_latest(force_refresh: bool = Query(default=False)) -> JSONResponse:
    await _build_and_store_dashboard_payload()

    if not LIVE_API_CORPUS_JSON_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="No live corpus JSON is available yet. Call /api/analysis/all first.",
        )

    return JSONResponse(content=json.loads(LIVE_API_CORPUS_JSON_PATH.read_text(encoding="utf-8")))


@app.get("/api/dashboard/history")
async def dashboard_history() -> JSONResponse:
    return JSONResponse(
        content={
            "items": [],
            "message": "Dashboard history is disabled because dashboard endpoints always return live data.",
        }
    )


@app.get("/api/dashboard/export/csv")
async def export_csv() -> StreamingResponse:
    client = LMSApiClient()
    raw_payload = await client.fetch_all()
    live_payload = await build_all_candidate_analysis(raw_payload)

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
    if live_payload.get("analysis_scope") == "multi_candidate":
        for candidate in live_payload.get("candidates", []):
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
        question_rows = live_payload.get("questions", [])

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
