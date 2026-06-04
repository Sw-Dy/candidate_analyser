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

from app.config import BASE_DIR, DATABASE_PATH
from app.database import fetch_latest_snapshot, initialize_database, save_snapshot
from app.models.schemas import DashboardResponse
from app.services.analytics import build_dashboard_payload
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


@app.get("/api/dashboard/analytics", response_model=DashboardResponse)
async def dashboard_analytics(force_refresh: bool = Query(default=True)) -> DashboardResponse:
    if not force_refresh:
        cached_payload = fetch_latest_snapshot(DATABASE_PATH)
        if cached_payload is not None:
            return DashboardResponse(data=cached_payload, source="cache")

    client = LMSApiClient()
    try:
        raw_payload = await client.fetch_all()
        logger.info("Upstream API payloads:\n%s", json.dumps(raw_payload.get("raw_apis", {}), indent=2, default=str))
        payload = await build_dashboard_payload(raw_payload)
        logger.info("Computed analytics snapshot:\n%s", json.dumps(payload, indent=2, default=str))
        payload["snapshot_id"] = save_snapshot(DATABASE_PATH, payload)
        return DashboardResponse(data=payload, source="live")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Dashboard analytics build failed")
        cached_payload = fetch_latest_snapshot(DATABASE_PATH)
        if cached_payload is not None:
            return DashboardResponse(data=cached_payload, source="cache")
        raise HTTPException(status_code=502, detail=f"Unable to build dashboard analytics: {exc}") from exc


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
        cached_payload = await build_dashboard_payload(raw_payload)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Question ID",
            "Question",
            "Domain",
            "Topic",
            "Difficulty",
            "Status",
            "Marks Obtained",
            "Full Marks",
            "Time Spent (s)",
        ]
    )
    for question in cached_payload["questions"]:
        writer.writerow(
            [
                question["question_id"],
                question["question_text"],
                question["domain"],
                question["topic"],
                question["difficulty"],
                question["status"],
                question["marks_obtained"],
                question["full_marks"],
                question["time_spent_seconds"],
            ]
        )

    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="student-assessment-analytics.csv"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)
