from typing import Any

from pydantic import BaseModel, Field


class ExportRow(BaseModel):
    question_id: int
    question_text: str
    domain: str
    topic: str
    difficulty: str
    status: str
    marks_obtained: float
    full_marks: float
    time_spent_seconds: float


class DomainMetric(BaseModel):
    domain: str
    total_questions: int
    attempted_questions: int
    correct_answers: int
    partial_answers: int = 0
    incorrect_answers: int
    marks_obtained: float
    total_marks: float
    score_percent: float = 0
    accuracy: float
    average_time_seconds: float
    classification: str
    weak_topics: list[str]


class DashboardPayload(BaseModel):
    student: dict[str, Any]
    exam: dict[str, Any]
    summary: dict[str, Any]
    domains: list[DomainMetric]
    questions: list[dict[str, Any]]
    strengths: list[str]
    weaknesses: list[str]
    skill_radar: dict[str, Any]
    rankings: list[dict[str, Any]]
    top_performer: dict[str, Any]
    ranking_summary: dict[str, Any]
    recommendations: list[str]
    recommended_courses: list[dict[str, Any]]
    raw_apis: dict[str, Any]
    generated_at: str


class DashboardResponse(BaseModel):
    data: DashboardPayload
    source: str = Field(description="Always live")
