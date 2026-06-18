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


@app.get("/api/analysis/candidate-exam")
@app.get("/api/analysis/candidate/exam")
async def analysis_candidate_exam_query(
    candidate_id: int = Query(...),
    exam_id: int = Query(...),
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
                sum(float(item.get("summary", {}).get("raw_accuracy", item.get("summary", {}).get("accuracy") or 0)) for item in attempts) / len(attempts),
                2,
            ),
            "average_marks_percent": round(
                sum(float(item.get("summary", {}).get("marks_percent", item.get("summary", {}).get("overall_score_percent") or 0)) for item in attempts)
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
    profile = candidate_payload.get("profile", {})
    candidate_name = candidate_payload.get("candidate_name") or profile.get("name") or f"Candidate {candidate_id}"
    ranked_rows = _rank_candidates_for_exam(analysis_payload, exam_id)
    selected_ranking = next(
        (row for row in ranked_rows if int(row.get("candidate_id") or 0) == candidate_id),
        {},
    )
    response = {
        "generated_at": generated_at,
        "source": source,
        "exam": primary_attempt.get("exam") or {"exam_id": exam_id, "name": f"Exam {exam_id}"},
        "selected_candidate_report": {
            "candidate": _build_candidate_basics(candidate_id, candidate_name, profile),
            "rank": selected_ranking.get("rank"),
            "total_candidates": len(ranked_rows),
            "summary": candidate_payload.get("summary", {}),
            "metrics": _build_candidate_metric_summary(candidate_payload),
            "attempts": _build_attempt_report_rows(attempts),
            "domains": _clean_domain_rows(primary_attempt.get("domains", [])),
            "strengths": primary_attempt.get("strengths", []),
            "weaknesses": primary_attempt.get("weaknesses", []),
            "skill_radar": primary_attempt.get("skill_radar", {}),
            "recommendations": primary_attempt.get("recommendations", []),
            "recommended_courses": primary_attempt.get("recommended_courses", []),
            "questions": _build_question_rows(attempts),
            "primary_attempt_id": primary_attempt.get("attempt_id"),
        },
        "benchmark": _build_exam_benchmark(exam_id, ranked_rows),
    }
    _validate_candidate_exam_response(response, candidate_id)
    return response


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


def _build_candidate_metric_summary(candidate_payload: dict) -> dict:
    attempts = candidate_payload.get("attempts", [])
    total_questions = sum(int(attempt.get("summary", {}).get("total_questions") or 0) for attempt in attempts)
    correct_answers = sum(int(attempt.get("summary", {}).get("correct_answers") or 0) for attempt in attempts)
    obtained_marks = sum(float(attempt.get("summary", {}).get("obtained_marks") or 0) for attempt in attempts)
    total_marks = sum(float(attempt.get("summary", {}).get("total_marks") or 0) for attempt in attempts)
    raw_accuracy = round((correct_answers / total_questions) * 100, 2) if total_questions else 0.0
    weighted_accuracy = round((obtained_marks / total_marks) * 100, 2) if total_marks else 0.0
    return {
        "raw_accuracy": raw_accuracy,
        "weighted_accuracy": weighted_accuracy,
        "marks_percent": weighted_accuracy,
        "obtained_marks": round(obtained_marks, 2),
        "total_marks": round(total_marks, 2),
        "correct_answers": correct_answers,
        "total_questions": total_questions,
    }


def _build_attempt_report_rows(attempts: list[dict]) -> list[dict]:
    rows = []
    for attempt in attempts:
        summary = attempt.get("summary", {})
        ranking_summary = attempt.get("ranking_summary", {})
        rows.append(
            {
                "attempt_id": attempt.get("attempt_id"),
                "exam_id": attempt.get("exam", {}).get("exam_id"),
                "exam_name": attempt.get("exam", {}).get("name"),
                "rank": ranking_summary.get("attempt_rank") or ranking_summary.get("current_candidate_rank"),
                "total_candidates": ranking_summary.get("total_candidates"),
                "raw_accuracy": summary.get("raw_accuracy", summary.get("accuracy", 0)),
                "weighted_accuracy": summary.get("weighted_accuracy", summary.get("overall_score_percent", 0)),
                "marks_percent": summary.get("marks_percent", summary.get("overall_score_percent", 0)),
                "obtained_marks": summary.get("obtained_marks", 0),
                "total_marks": summary.get("total_marks", 0),
                "time_taken_seconds": summary.get("time_taken_seconds", 0),
            }
        )
    return rows


def _rank_candidates_for_exam(analysis_payload: dict, exam_id: int) -> list[dict]:
    candidate_analyses = analysis_payload.get("candidate_analyses", {})
    rows = []
    for row in analysis_payload.get("ranked_candidates", []):
        candidate_id = int(row.get("candidate_id") or 0)
        candidate_payload = candidate_analyses.get(str(candidate_id), {})
        if _filter_candidate_analysis_by_exam(candidate_payload, exam_id) is not None:
            rows.append(dict(row))
    return rows


def _build_exam_benchmark(exam_id: int, ranked_rows: list[dict]) -> dict:
    total_candidates = len(ranked_rows)
    if not ranked_rows:
        return {
            "exam_id": exam_id,
            "total_candidates": 0,
            "leaderboard": [],
            "averages": {},
        }
    return {
        "exam_id": exam_id,
        "total_candidates": total_candidates,
        "top_performer": ranked_rows[0],
        "leaderboard": ranked_rows,
        "averages": {
            "raw_accuracy": round(
                sum(float(row.get("accuracy") or 0) for row in ranked_rows) / total_candidates,
                2,
            ),
            "marks_percent": round(
                sum(float(row.get("marks_percent") or 0) for row in ranked_rows) / total_candidates,
                2,
            ),
            "composite_score": round(
                sum(float(row.get("composite_score") or 0) for row in ranked_rows) / total_candidates,
                2,
            ),
        },
    }


def _validate_candidate_exam_response(response: dict, candidate_id: int) -> None:
    benchmark = response.get("benchmark", {})
    leaderboard = benchmark.get("leaderboard", [])
    total_candidates = int(benchmark.get("total_candidates") or 0)
    if total_candidates != len(leaderboard):
        raise HTTPException(
            status_code=500,
            detail="Ranking validation failed: benchmark total_candidates does not match leaderboard length.",
        )

    ranks = [int(row.get("rank") or 0) for row in leaderboard]
    if sorted(ranks) != list(range(1, total_candidates + 1)):
        raise HTTPException(status_code=500, detail="Ranking validation failed: leaderboard ranks are inconsistent.")

    selected_report = response.get("selected_candidate_report", {})
    leaderboard_row = next(
        (row for row in leaderboard if int(row.get("candidate_id") or 0) == candidate_id),
        None,
    )
    if leaderboard_row is None:
        raise HTTPException(status_code=500, detail="Ranking validation failed: selected candidate missing from leaderboard.")

    expected_rank = int(leaderboard_row.get("rank") or 0)
    observed_ranks = {int(selected_report.get("rank") or 0)}
    for attempt in selected_report.get("attempts", []):
        observed_ranks.add(int(attempt.get("rank") or 0))
        if int(attempt.get("total_candidates") or 0) != total_candidates:
            raise HTTPException(
                status_code=500,
                detail="Ranking validation failed: selected attempt total_candidates mismatch.",
            )
    if observed_ranks != {expected_rank}:
        raise HTTPException(status_code=500, detail="Ranking validation failed: selected candidate rank mismatch.")


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
