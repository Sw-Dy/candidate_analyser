from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from app.services.recommendation import RecommendationService
from app.services.skill_intelligence import AIEnrichmentError, SkillIntelligenceService


DEFAULT_LABEL = "Pending AI Label"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _classify_strength(accuracy: float) -> str:
    if accuracy >= 80:
        return "Strong"
    if accuracy >= 50:
        return "Moderate"
    return "Weak"


def _first_present_number(payload: dict[str, Any], keys: list[str]) -> tuple[float, str | None]:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return _safe_float(payload.get(key)), key
    return 0.0, None


def _first_positive_number(payload: dict[str, Any], keys: list[str]) -> tuple[float, str | None]:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            value = _safe_float(payload.get(key))
            if value > 0:
                return value, key
    return 0.0, None


def _first_present_value(payload: dict[str, Any], keys: list[str]) -> tuple[Any, str | None]:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key), key
    return None, None


def _first_nonempty_label(payload: dict[str, Any], keys: list[str]) -> tuple[str, str | None]:
    invalid = {"", "unknown", "n/a", "na", "none", "null"}
    for key in keys:
        if key not in payload:
            continue
        label = str(payload.get(key) or "").strip()
        if label and label.lower() not in invalid:
            return label, key
    return "", None


def _extract_full_marks(question: dict[str, Any]) -> tuple[float, str | None]:
    return _first_present_number(
        question,
        [
            "Full_Marks",
            "FullMarks",
            "full_marks",
            "QuestionMarks",
            "Question_Marks",
            "TotalQuestionMarks",
            "Total_Question_Marks",
            "MaxMarks",
            "MaximumMarks",
            "Marks",
            "TotalMarks",
        ],
    )


def _extract_marks_obtained(question: dict[str, Any], full_marks: float, is_correct_without_marks: bool) -> tuple[float, str]:
    value, key = _first_present_number(
        question,
        [
            "EvaluatedMarks",
            "Evaluated_Marks",
            "ObtainedMarks",
            "Obtained_Marks",
            "MarksObtained",
            "Marks_Obtained",
            "CandidateMarks",
            "Candidate_Marks",
            "QuestionObtainedMarks",
            "Question_Obtained_Marks",
            "QuestionMarksObtained",
            "Question_Marks_Obtained",
            "CandidateObtainedMarks",
            "Candidate_Obtained_Marks",
            "AnswerMarks",
            "Answer_Marks",
            "MarksAwarded",
            "Marks_Awarded",
            "EvaluatedScore",
            "EvaluatorMarks",
            "Evaluator_Marks",
            "Score",
            "score",
            "marks_obtained",
            "obtained_marks",
        ],
    )
    if key is not None:
        return value, key
    return (full_marks if is_correct_without_marks else 0.0), "legacy_correctness_fallback"


def _build_local_strengths_and_weaknesses(question_rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    topic_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"questions": 0, "marks_obtained": 0.0, "total_marks": 0.0}
    )

    for row in question_rows:
        topic = str(row.get("topic") or row.get("domain") or DEFAULT_LABEL).strip()
        if not topic:
            topic = DEFAULT_LABEL
        stats = topic_stats[topic]
        stats["questions"] += 1
        stats["marks_obtained"] += float(row.get("marks_obtained") or 0)
        stats["total_marks"] += float(row.get("full_marks") or 0)

    strengths = []
    weaknesses = []
    for topic, stats in topic_stats.items():
        percent = round((stats["marks_obtained"] / stats["total_marks"]) * 100, 2) if stats["total_marks"] else 0.0
        label = f"{topic} ({round(stats['marks_obtained'], 2)}/{round(stats['total_marks'], 2)} marks)"
        item = {
            "topic": topic,
            "label": label,
            "total": int(stats["questions"]),
            "score": percent,
        }
        if percent >= 70:
            strengths.append(item)
        elif percent < 50:
            weaknesses.append(item)

    strengths.sort(key=lambda item: (item["score"], item["total"], item["topic"]), reverse=True)
    weaknesses.sort(key=lambda item: (item["score"], item["total"], item["topic"]))
    return [item["label"] for item in strengths], [item["label"] for item in weaknesses]


def _build_domain_rows(question_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    domain_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in question_rows:
        domain = str(row.get("domain") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
        domain_buckets[domain].append(row)

    domain_rows = []
    for domain in sorted(domain_buckets):
        rows = domain_buckets[domain]
        domain_attempted = sum(1 for row in rows if row["is_answered"])
        domain_correct = sum(1 for row in rows if row["is_correct"])
        domain_partial = sum(1 for row in rows if row["status"] == "Partial")
        domain_incorrect = sum(1 for row in rows if row["status"] == "Incorrect")
        domain_total_marks = round(sum(row["full_marks"] for row in rows), 2)
        domain_marks = round(sum(row["marks_obtained"] for row in rows), 2)
        domain_score_percent = round((domain_marks / domain_total_marks) * 100, 2) if domain_total_marks else 0.0
        domain_accuracy = round((domain_correct / len(rows)) * 100, 2) if rows else 0.0
        weak_topic_scores: dict[str, dict[str, float]] = defaultdict(
            lambda: {"marks_obtained": 0.0, "total_marks": 0.0}
        )
        for row in rows:
            topic = str(row.get("topic") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
            weak_topic_scores[topic]["marks_obtained"] += float(row.get("marks_obtained") or 0)
            weak_topic_scores[topic]["total_marks"] += float(row.get("full_marks") or 0)

        weak_topics = sorted(
            (
                (
                    topic,
                    (stats["marks_obtained"] / stats["total_marks"] * 100) if stats["total_marks"] else 0.0,
                )
                for topic, stats in weak_topic_scores.items()
            ),
            key=lambda item: item[1],
        )

        domain_rows.append(
            {
                "domain": domain,
                "total_questions": len(rows),
                "attempted_questions": domain_attempted,
                "correct_answers": domain_correct,
                "partial_answers": domain_partial,
                "incorrect_answers": domain_incorrect,
                "marks_obtained": domain_marks,
                "total_marks": domain_total_marks,
                "score_percent": domain_score_percent,
                "accuracy": domain_accuracy,
                "average_time_seconds": round(
                    sum(row["time_spent_seconds"] for row in rows) / domain_attempted, 2
                )
                if domain_attempted
                else 0.0,
                "classification": _classify_strength(domain_score_percent) if rows else "No Data",
                "weak_topics": [topic for topic, percent in weak_topics if percent < 70][:3],
            }
        )

    domain_rows.sort(key=lambda item: (item["score_percent"], item["total_questions"]), reverse=True)
    return domain_rows


def _extract_answers(question: dict[str, Any]) -> tuple[str, str]:
    selected_option = next(
        (
            option.get("Candidate_Selected_Option_Text")
            or option.get("CandidateSelectedOptionText")
            or option.get("Option_Text")
            or ""
            for option in question.get("Options", [])
            if option.get("Is_Selected_By_Candidate") or option.get("IsSelectedByCandidate")
        ),
        "",
    )
    correct_option = next(
        (
            option.get("Option_Text", "")
            for option in question.get("Options", [])
            if option.get("Is_Correct_Option") or option.get("IsCorrectOption")
        ),
        "",
    )
    selected_text = selected_option or question.get("Candidate_Answer_Text") or question.get("CandidateAnswer") or ""
    correct_text = correct_option or question.get("Model_Answer_Text") or question.get("CorrectAnswer") or ""
    return str(selected_text), str(correct_text)


def _is_correct_by_options(question: dict[str, Any]) -> bool:
    options = question.get("Options", [])
    return any(
        (option.get("Is_Correct_Option") or option.get("IsCorrectOption"))
        and (option.get("Is_Selected_By_Candidate") or option.get("IsSelectedByCandidate"))
        for option in options
    )


def _is_correct_from_marks(marks_obtained: float, full_marks: float, fallback_correct: bool) -> bool:
    if full_marks > 0:
        return marks_obtained >= full_marks
    if marks_obtained > 0:
        return True
    return fallback_correct


def _question_status(*, is_answered: bool, is_correct: bool, marks_obtained: float, full_marks: float) -> str:
    if not is_answered:
        return "Skipped"
    if is_correct:
        return "Correct"
    if marks_obtained > 0 and (full_marks <= 0 or marks_obtained < full_marks):
        return "Partial"
    return "Incorrect"


def _flatten_profile_sections(candidate_profile: dict[str, Any]) -> list[dict[str, Any]]:
    sections = candidate_profile.get("sections", candidate_profile)
    flattened: list[dict[str, Any]] = []
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, list):
                flattened.extend(item for item in section if isinstance(item, dict))
            elif isinstance(section, dict):
                flattened.append(section)
    elif isinstance(sections, dict):
        flattened.append(sections)
    return flattened


def _build_candidate_profile(candidate_profile: dict[str, Any]) -> dict[str, Any]:
    flattened = _flatten_profile_sections(candidate_profile)
    position = next(
        (str(item.get("position", "")).strip() for item in flattened if item.get("position")),
        "Not provided",
    )
    computer_proficiency = next(
        (
            str(item.get("cmputerProficiency", "")).strip()
            for item in flattened
            if item.get("cmputerProficiency")
        ),
        "",
    )
    languages = sorted(
        {
            str(item.get("languagename", "")).strip()
            for item in flattened
            if item.get("languagename")
        }
    )
    education = [
        {
            "level": str(item.get("eduname", "")).strip(),
            "degree": str(item.get("degreename", "")).strip(),
            "marks": str(item.get("marks", "")).strip(),
            "institute": str(item.get("institute", "")).strip(),
        }
        for item in flattened
        if item.get("eduname")
    ]
    return {
        "position": position,
        "computer_proficiency": computer_proficiency,
        "languages": languages,
        "education": education[:5],
    }


def _question_speed_score(time_spent_seconds: float, average_time_seconds: float) -> float:
    baseline = max(average_time_seconds, 1.0)
    speed_ratio = time_spent_seconds / baseline if time_spent_seconds else 1.0
    score = 100 - ((speed_ratio - 1) * 35)
    return round(max(25.0, min(100.0, score)), 2)


def _build_skill_radar(
    *,
    question_rows: list[dict[str, Any]],
    average_time_seconds: float,
    source: str,
) -> dict[str, Any]:
    domain_scores: dict[str, list[float]] = defaultdict(list)
    domain_skill_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    domain_question_ids: dict[str, set[int]] = defaultdict(set)

    for row in question_rows:
        domain = str(row.get("domain") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
        marks_percent = (row["marks_obtained"] / row["full_marks"] * 100) if row["full_marks"] else 0.0
        accuracy_score = 100.0 if row["is_correct"] else (50.0 if row["status"] == "Partial" else 0.0)
        speed_score = _question_speed_score(row["time_spent_seconds"], average_time_seconds)
        question_score = round((marks_percent * 0.70) + (accuracy_score * 0.15) + (speed_score * 0.15), 2)
        domain_scores[domain].append(question_score)
        domain_question_ids[domain].add(row["question_id"])

        skills = [row.get("primary_skill")] + list(row.get("supporting_skills", []))
        deduped_skills = [skill for skill in dict.fromkeys(skills) if skill]
        for index, skill in enumerate(deduped_skills):
            weight = 1.0 if index == 0 else 0.6
            domain_skill_scores[domain][skill].append(question_score * weight)

    labels = []
    scores = []
    details = []
    for domain in sorted(domain_scores):
        values = domain_scores.get(domain, [])
        score = round(sum(values) / len(values), 2) if values else 0.0
        labels.append(domain)
        scores.append(score)
        skills = []
        for skill, skill_values in sorted(domain_skill_scores.get(domain, {}).items()):
            skill_score = round(sum(skill_values) / len(skill_values), 2) if skill_values else 0.0
            skills.append(
                {
                    "skill": skill,
                    "score": skill_score,
                    "question_count": sum(
                        1
                        for row in question_rows
                        if row.get("domain") == domain
                        and skill in [row.get("primary_skill")] + list(row.get("supporting_skills", []))
                    ),
                }
            )
        details.append(
            {
                "domain": domain,
                "score": score,
                "question_count": len(domain_question_ids.get(domain, set())),
                "skills": skills,
            }
        )

    return {
        "labels": labels,
        "scores": scores,
        "details": details,
        "source": source,
    }


def _extract_record_questions(record: dict[str, Any]) -> list[dict[str, Any]]:
    questions = record.get("Questions") or record.get("questions") or []
    return [item for item in questions if isinstance(item, dict)]


def _compute_record_accuracy(record: dict[str, Any]) -> float:
    for key in ["accuracy", "Accuracy", "AccuracyPercent", "accuracy_percent"]:
        if key in record:
            return round(_safe_float(record.get(key)), 2)

    questions = _extract_record_questions(record)
    attempted = sum(1 for item in questions if item.get("IsAnswered") or item.get("is_answered"))
    correct = 0
    for item in questions:
        options = item.get("Options") or item.get("options") or []
        is_correct = any(
            (option.get("Is_Correct_Option") or option.get("IsCorrectOption"))
            and (option.get("Is_Selected_By_Candidate") or option.get("IsSelectedByCandidate"))
            for option in options
            if isinstance(option, dict)
        )
        if is_correct:
            correct += 1
    total_questions = len(questions)
    return round((correct / total_questions) * 100, 2) if total_questions else 0.0


def _compute_record_marks(record: dict[str, Any], fallback_total_marks: float = 0.0) -> tuple[float, float]:
    obtained_marks, obtained_source = _first_present_number(
        record,
        ["ObtainedMarks", "obtained_marks", "MarksObtained", "Score"],
    )
    total_marks, total_source = _first_present_number(
        record,
        ["TotalMarks", "total_marks", "FullMarks", "MaxMarks"],
    )
    questions = _extract_record_questions(record)
    if obtained_source is None and questions:
        question_obtained = 0.0
        for question in questions:
            full_marks, _ = _extract_full_marks(question)
            option_correct = _is_correct_by_options(question)
            marks, _ = _extract_marks_obtained(question, full_marks, option_correct)
            question_obtained += marks
        obtained_marks = question_obtained
    if total_source is None and questions:
        total_marks = sum(_extract_full_marks(question)[0] for question in questions)
    if total_source is None and not total_marks:
        total_marks = fallback_total_marks
    return round(obtained_marks, 2), round(total_marks, 2)


def _compute_record_total_time(record: dict[str, Any]) -> int:
    explicit = _safe_int(
        record.get("TimeTakenSeconds")
        or record.get("time_taken_seconds")
        or record.get("DurationSeconds")
        or record.get("duration_seconds")
    )
    if explicit:
        return explicit

    started_on = _safe_datetime(record.get("StartedOn") or record.get("started_on"))
    submitted_on = _safe_datetime(record.get("SubmittedOn") or record.get("submitted_on"))
    if started_on and submitted_on:
        return max(0, int((submitted_on - started_on).total_seconds()))
    return 0


def _extract_exam_duration_minutes(*, metadata: dict[str, Any], summary: dict[str, Any], attempt: dict[str, Any]) -> int:
    for payload in [metadata, summary, attempt]:
        value, key = _first_positive_number(
            payload,
            [
                "Exam_Duration",
                "ExamDuration",
                "ExamDurationMinutes",
                "DurationMinutes",
                "Duration_Minutes",
                "TimeDuration",
                "Time_Duration",
                "TotalTime",
                "Total_Time",
            ],
        )
        if key is not None:
            return int(value)

        seconds, seconds_key = _first_positive_number(
            payload,
            ["ExamDurationSeconds", "DurationSeconds", "Duration_Seconds"],
        )
        if seconds_key is not None:
            return int(round(seconds / 60))
    return 0


def _extract_evaluation_type(*, metadata: dict[str, Any], summary: dict[str, Any], attempt: dict[str, Any]) -> str:
    for payload in [metadata, summary, attempt]:
        label, _ = _first_nonempty_label(
            payload,
            [
                "Evaluation_Type_Name",
                "EvaluationTypeName",
                "Evaluation_Type",
                "EvaluationType",
                "Exam_Evaluation_Type",
                "ExamEvaluationType",
                "QuestionEvaluationType",
                "AssessmentType",
                "Assessment_Type",
            ],
        )
        if label:
            return label
    return "Unknown"


def _validate_exam_metadata(exam: dict[str, Any]) -> None:
    if int(exam.get("duration_minutes") or 0) <= 0:
        raise ValueError(
            f"Exam metadata validation failed for exam_id {exam.get('exam_id')}: duration_minutes must be greater than zero."
        )
    evaluation_type = str(exam.get("evaluation_type") or "").strip()
    if not evaluation_type or evaluation_type.lower() == "unknown":
        raise ValueError(
            f"Exam metadata validation failed for exam_id {exam.get('exam_id')}: evaluation_type is missing."
        )


def _reconcile_missing_question_marks(
    *,
    question_rows: list[dict[str, Any]],
    target_obtained_marks: float,
) -> None:
    current_total = round(sum(float(row.get("marks_obtained") or 0) for row in question_rows), 2)
    missing_total = round(target_obtained_marks - current_total, 2)
    if missing_total <= 0:
        return

    candidates = [
        row
        for row in question_rows
        if row.get("is_answered")
        and str(row.get("marks_source") or "").endswith("fallback")
        and float(row.get("marks_obtained") or 0) < float(row.get("full_marks") or 0)
    ]
    if not candidates:
        return

    total_capacity = round(
        sum(float(row.get("full_marks") or 0) - float(row.get("marks_obtained") or 0) for row in candidates),
        2,
    )
    if total_capacity <= 0:
        return

    for index, row in enumerate(candidates):
        capacity = float(row.get("full_marks") or 0) - float(row.get("marks_obtained") or 0)
        if index == len(candidates) - 1:
            award = min(capacity, missing_total)
        else:
            award = min(capacity, round((capacity / total_capacity) * missing_total, 2))
        if award <= 0:
            continue
        row["marks_obtained"] = round(float(row.get("marks_obtained") or 0) + award, 2)
        row["marks_percent"] = (
            round((float(row["marks_obtained"]) / float(row.get("full_marks") or 0)) * 100, 2)
            if float(row.get("full_marks") or 0)
            else 0.0
        )
        row["marks_source"] = "attempt_total_reconciled"
        row["is_correct"] = _is_correct_from_marks(
            float(row["marks_obtained"]),
            float(row.get("full_marks") or 0),
            bool(row.get("is_correct")),
        )
        row["status"] = _question_status(
            is_answered=bool(row.get("is_answered")),
            is_correct=bool(row.get("is_correct")),
            marks_obtained=float(row["marks_obtained"]),
            full_marks=float(row.get("full_marks") or 0),
        )
        missing_total = round(missing_total - award, 2)
        if missing_total <= 0:
            break


def _build_rankings(
    *,
    all_candidate_attempts: list[dict[str, Any]],
    current_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    exam_id = current_payload["exam"]["exam_id"]
    current_candidate_id = current_payload["student"]["candidate_id"]
    ranking_rows = []

    source_attempts = []
    for record in all_candidate_attempts:
        record_exam_id = _safe_int(
            record.get("Exam_Id")
            or record.get("ExamID")
            or record.get("ExamId")
            or record.get("exam_id")
            or record.get("ID")
        )
        if record_exam_id and record_exam_id != exam_id:
            continue
        source_attempts.append(record)

    if not source_attempts:
        source_attempts = [
            {
                "Candidate_Id": current_candidate_id,
                "Exam_Id": exam_id,
                "ObtainedMarks": current_payload["summary"]["obtained_marks"],
                "TotalMarks": current_payload["summary"]["total_marks"],
                "accuracy": current_payload["summary"]["accuracy"],
                "TimeTakenSeconds": current_payload["summary"]["time_taken_seconds"],
                "Questions": [],
                "candidate_name": current_payload["student"]["name"],
            }
        ]

    for record in source_attempts:
        candidate_id = _safe_int(
            record.get("Candidate_Id")
            or record.get("CandidateId")
            or record.get("candidateid")
            or record.get("candidateId")
            or record.get("UserId")
        )
        questions = _extract_record_questions(record)
        attempted_questions = (
            _safe_int(record.get("AttemptedQuestions") or record.get("attempted_questions"))
            or sum(1 for item in questions if item.get("IsAnswered") or item.get("is_answered"))
        )
        total_questions = len(questions) or current_payload["summary"]["total_questions"]
        total_time_seconds = _compute_record_total_time(record)
        avg_time = round(total_time_seconds / attempted_questions, 2) if attempted_questions else 0.0
        if not avg_time and candidate_id == current_candidate_id:
            avg_time = current_payload["summary"]["average_time_per_question_seconds"]
        obtained_marks, total_marks = _compute_record_marks(
            record,
            fallback_total_marks=current_payload["summary"]["total_marks"],
        )
        marks_percent = round((obtained_marks / total_marks) * 100, 2) if total_marks else 0.0
        accuracy = _compute_record_accuracy(record)
        ranking_rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_name": str(
                    record.get("candidate_name")
                    or record.get("Candidate_Name")
                    or record.get("CandidateName")
                    or (current_payload["student"]["name"] if candidate_id == current_candidate_id else f"Candidate {candidate_id}")
                ).strip(),
                "accuracy": accuracy,
                "obtained_marks": obtained_marks,
                "total_marks": total_marks,
                "marks_percent": marks_percent,
                "time_taken_seconds": total_time_seconds,
                "average_time_per_question_seconds": avg_time,
                "attempted_questions": attempted_questions or current_payload["summary"]["attempted_questions"],
                "total_questions": total_questions,
            }
        )

    valid_speed_rows = [row for row in ranking_rows if row["average_time_per_question_seconds"] > 0]
    min_speed = min((row["average_time_per_question_seconds"] for row in valid_speed_rows), default=0.0)
    max_speed = max((row["average_time_per_question_seconds"] for row in valid_speed_rows), default=0.0)

    for row in ranking_rows:
        if not valid_speed_rows or math.isclose(max_speed, min_speed):
            row["speed_score"] = 100.0 if row["attempted_questions"] else 0.0
        elif row["average_time_per_question_seconds"] <= 0:
            row["speed_score"] = 0.0
        else:
            row["speed_score"] = round(
                ((max_speed - row["average_time_per_question_seconds"]) / (max_speed - min_speed)) * 100,
                2,
            )

        row["composite_score"] = round(
            (row["marks_percent"] * 0.65) + (row["accuracy"] * 0.20) + (row["speed_score"] * 0.15),
            2,
        )

    ranking_rows.sort(
        key=lambda item: (
            item["composite_score"],
            item["accuracy"],
            item["marks_percent"],
            -item["average_time_per_question_seconds"],
        ),
        reverse=True,
    )

    for index, row in enumerate(ranking_rows, start=1):
        row["rank"] = index

    top_performer = ranking_rows[0] if ranking_rows else {}
    current_candidate_rank = next(
        (row for row in ranking_rows if row["candidate_id"] == current_candidate_id),
        ranking_rows[0] if ranking_rows else {},
    )

    rank_summary = {
        "current_candidate_rank": current_candidate_rank.get("rank"),
        "total_candidates": len(ranking_rows),
        "ranking_source": "all_candidate_attempts" if all_candidate_attempts else "single_candidate_fallback",
        "leader_gap_score": round(
            max(0.0, (top_performer.get("composite_score", 0.0) - current_candidate_rank.get("composite_score", 0.0))),
            2,
        ),
    }
    return ranking_rows, top_performer, rank_summary


async def build_dashboard_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
    attempt = raw_payload.get("attempt", {})
    if not attempt:
        raise ValueError("Exam Attempt Answer API did not return a usable attempt payload")

    questions = attempt.get("Questions", [])
    started_on = _safe_datetime(attempt.get("StartedOn") or attempt.get("ExamStartedOn"))
    submitted_on = _safe_datetime(attempt.get("SubmittedOn") or attempt.get("ExamSubmittedOn"))
    total_time_seconds = 0
    if started_on and submitted_on:
        total_time_seconds = int((submitted_on - started_on).total_seconds())
    if not total_time_seconds:
        total_time_seconds = _safe_int(attempt.get("TimeTakenSeconds") or raw_payload.get("summary", {}).get("TimeTakenSeconds"))

    attempted_questions = sum(1 for question in questions if question.get("IsAnswered") or question.get("is_answered"))
    total_questions = len(questions)
    equal_time = round(total_time_seconds / attempted_questions, 2) if attempted_questions else 0.0

    question_rows = []

    for question in questions:
        selected_answer, correct_answer = _extract_answers(question)
        is_answered = bool(question.get("IsAnswered"))
        if not is_answered:
            is_answered = bool(question.get("is_answered"))
        full_marks, full_marks_source = _extract_full_marks(question)
        option_correct = _is_correct_by_options(question)
        marks_obtained, marks_source = _extract_marks_obtained(question, full_marks, option_correct)
        is_correct = _is_correct_from_marks(marks_obtained, full_marks, option_correct)
        time_spent = equal_time if is_answered else 0.0
        status = _question_status(
            is_answered=is_answered,
            is_correct=is_correct,
            marks_obtained=marks_obtained,
            full_marks=full_marks,
        )

        row = {
            "question_id": int(question.get("Question_Id") or question.get("QuestionId") or 0),
            "question_text": str(question.get("Question_Text", "")),
            "question_type": str(question.get("Question_Type_Name") or question.get("QuestionTypeName") or "Unknown"),
            "domain": DEFAULT_LABEL,
            "topic": DEFAULT_LABEL,
            "difficulty": str(
                raw_payload.get("metadata", {}).get("Exam_Level_Name")
                or raw_payload.get("summary", {}).get("Exam_Level_Name")
                or "Intermediate"
            ),
            "mapping_source": "pending_ai",
            "status": status,
            "is_answered": is_answered,
            "is_correct": is_correct,
            "marks_obtained": round(marks_obtained, 2),
            "full_marks": round(full_marks, 2),
            "marks_percent": round((marks_obtained / full_marks) * 100, 2) if full_marks else 0.0,
            "marks_source": marks_source,
            "full_marks_source": full_marks_source,
            "negative_marks": float(question.get("Negative_Marks") or 0),
            "time_spent_seconds": time_spent,
            "selected_answer": selected_answer,
            "correct_answer": correct_answer,
            "primary_skill": None,
            "supporting_skills": [],
            "difficulty_label": "Intermediate",
            "difficulty_rating": 3,
        }
        question_rows.append(row)

    summary = raw_payload.get("summary", {})
    summary_obtained_marks, summary_obtained_source = _first_present_number(
        summary,
        ["ObtainedMarks", "obtained_marks", "MarksObtained", "Score"],
    )
    summary_total_marks, summary_total_source = _first_present_number(
        summary,
        ["TotalMarks", "total_marks", "FullMarks", "MaxMarks"],
    )
    if summary_obtained_source is not None:
        _reconcile_missing_question_marks(
            question_rows=question_rows,
            target_obtained_marks=summary_obtained_marks,
        )
    obtained_marks = round(
        summary_obtained_marks if summary_obtained_source is not None else sum(row["marks_obtained"] for row in question_rows),
        2,
    )
    total_marks = round(
        summary_total_marks if summary_total_source is not None else sum(row["full_marks"] for row in question_rows),
        2,
    )
    correct_answers = sum(1 for row in question_rows if row["is_correct"])
    partial_answers = sum(1 for row in question_rows if row["status"] == "Partial")
    incorrect_answers = sum(1 for row in question_rows if row["status"] == "Incorrect")
    raw_accuracy = round((correct_answers / total_questions) * 100, 2) if total_questions else 0.0
    weighted_accuracy = round((obtained_marks / total_marks) * 100, 2) if total_marks else 0.0
    average_time = round((total_time_seconds / attempted_questions), 2) if attempted_questions else 0.0

    strengths, weaknesses = _build_local_strengths_and_weaknesses(question_rows)

    metadata = raw_payload.get("metadata", {})
    candidate = raw_payload.get("candidate", {})
    candidate_profile = _build_candidate_profile(raw_payload.get("candidate_profile", {}))
    generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    payload = {
        "student": {
            "candidate_id": int(
                candidate.get("candidateid")
                or attempt.get("Candidate_Id")
                or attempt.get("CandidateId")
                or attempt.get("candidateId")
                or attempt.get("candidateid")
                or 0
            ),
            "registration_number": candidate.get("registrationnumber", "Unavailable"),
            "name": " ".join(
                part for part in [
                    str(candidate.get("firstname", "")).strip(),
                    str(candidate.get("middlename", "")).strip(),
                    str(candidate.get("lastname", "")).strip(),
                ] if part
            )
            or "Unknown Student",
            "course": candidate.get("postname") or candidate.get("professionalExperience") or "Not provided",
            "batch": candidate.get("Applicationstatus") or "Not provided",
            "mobile": candidate.get("mobile", "N/A"),
            "gender": candidate.get("gender", "N/A"),
            "applied_position": candidate_profile.get("position", "Not provided"),
            "languages": candidate_profile.get("languages", []),
            "computer_proficiency": candidate_profile.get("computer_proficiency", ""),
        },
        "exam": {
            "exam_id": int(attempt.get("Exam_Id") or attempt.get("ExamId") or summary.get("ID") or summary.get("ExamId") or 0),
            "name": metadata.get("Exam_Name") or attempt.get("Exam_Name") or attempt.get("ExamName") or summary.get("Exam_Name") or summary.get("ExamName") or "Assessment",
            "duration_minutes": _extract_exam_duration_minutes(
                metadata=metadata,
                summary=summary,
                attempt=attempt,
            ),
            "difficulty": metadata.get("Exam_Level_Name") or summary.get("Exam_Level_Name") or "Intermediate",
            "total_questions": total_questions,
            "evaluation_type": _extract_evaluation_type(
                metadata=metadata,
                summary=summary,
                attempt=attempt,
            ),
        },
        "summary": {
            "overall_score_percent": weighted_accuracy,
            "marks_percent": weighted_accuracy,
            "raw_accuracy": raw_accuracy,
            "weighted_accuracy": weighted_accuracy,
            "obtained_marks": obtained_marks,
            "total_marks": total_marks,
            "correct_answers": correct_answers,
            "partial_answers": partial_answers,
            "incorrect_answers": incorrect_answers,
            "attempted_questions": attempted_questions,
            "total_questions": total_questions,
            "accuracy": raw_accuracy,
            "time_taken_seconds": total_time_seconds,
            "time_taken_display": _seconds_to_display(total_time_seconds),
            "average_time_per_question_seconds": average_time,
            "correct_vs_incorrect_ratio": round(
                correct_answers / incorrect_answers, 2
            )
            if incorrect_answers
            else float(correct_answers),
        },
        "domains": _build_domain_rows(question_rows),
        "questions": question_rows,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "skill_radar": {"labels": [], "scores": [], "details": [], "source": "pending"},
        "rankings": [],
        "top_performer": {},
        "ranking_summary": {},
        "recommendations": [],
        "recommended_courses": [],
        "raw_apis": raw_payload.get("raw_apis", {}),
        "generated_at": generated_at,
    }
    _validate_exam_metadata(payload["exam"])

    skill_service = SkillIntelligenceService()
    skill_result = await skill_service.enrich(
        candidate_profile=candidate_profile,
        exam=payload["exam"],
        questions=question_rows,
    )
    question_intelligence = {
        item["question_id"]: item
        for item in skill_result.get("questions", [])
        if item.get("question_id") is not None
    }
    missing_ai_labels = [
        row["question_id"]
        for row in payload["questions"]
        if row["question_id"] not in question_intelligence
    ]
    if missing_ai_labels:
        raise AIEnrichmentError(f"ChatGPT did not return labels for question ids: {missing_ai_labels}")
    for row in payload["questions"]:
        intelligence = question_intelligence.get(row["question_id"], {})
        row["domain"] = _ai_label_or_none(intelligence.get("domain"))
        row["topic"] = _ai_label_or_none(intelligence.get("topic"))
        row["primary_skill"] = _ai_label_or_none(intelligence.get("primary_skill"))
        row["supporting_skills"] = intelligence.get("supporting_skills", [])
        row["difficulty_label"] = intelligence.get("difficulty_label") or row["difficulty"]
        row["difficulty_rating"] = intelligence.get("difficulty_rating") or 3
        row["mapping_source"] = intelligence.get("mapping_source") or skill_result.get("source", "ai_error")
        row["label_quality"] = intelligence.get("label_quality", "specific")
        row["label_warnings"] = intelligence.get("label_warnings", [])

    payload["domains"] = _build_domain_rows(payload["questions"])
    strengths_result = await skill_service.summarize_strengths_weaknesses(
        candidate_profile=candidate_profile,
        exam=payload["exam"],
        summary=payload["summary"],
        domains=payload["domains"],
        questions=payload["questions"],
    )
    payload["strengths"] = strengths_result["strengths"]
    payload["weaknesses"] = strengths_result["weaknesses"]

    payload["skill_radar"] = _build_skill_radar(
        question_rows=payload["questions"],
        average_time_seconds=average_time,
        source=skill_result.get("source", "ai"),
    )

    rankings, top_performer, ranking_summary = _build_rankings(
        all_candidate_attempts=raw_payload.get("all_candidate_attempts", []),
        current_payload=payload,
    )
    payload["rankings"] = rankings
    payload["top_performer"] = top_performer
    payload["ranking_summary"] = ranking_summary

    recommendation_service = RecommendationService()
    recommendation_result = await recommendation_service.generate(
        payload,
        raw_payload.get("course_list", []),
    )
    payload["recommendations"] = recommendation_result["recommendations"]
    payload["recommended_courses"] = recommendation_result["recommended_courses"]
    payload["raw_apis"]["analysis_api"] = recommendation_result["raw_api"]
    payload["raw_apis"]["skill_intelligence_api"] = skill_result["raw_api"]
    payload["raw_apis"]["strength_weakness_api"] = strengths_result["raw_api"]
    return payload


async def build_all_candidate_analysis(raw_payload: dict[str, Any]) -> dict[str, Any]:
    request_context = raw_payload.get("request_context", {})
    requested_candidate_id = _safe_int(request_context.get("candidate_id"))
    requested_exam_id = _safe_int(request_context.get("exam_id"))
    attempts_by_candidate: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in raw_payload.get("all_candidate_attempts", []):
        if requested_exam_id:
            record_exam_id = _safe_int(
                record.get("Exam_Id")
                or record.get("ExamID")
                or record.get("ExamId")
                or record.get("exam_id")
                or record.get("ID")
            )
            if record_exam_id and record_exam_id != requested_exam_id:
                continue
        candidate_id = _candidate_id_from_record(record)
        if candidate_id:
            attempts_by_candidate[candidate_id].append(record)

    default_candidate_id = _safe_int(raw_payload.get("candidate", {}).get("candidateid"))
    default_attempt_exam_id = _safe_int(
        raw_payload.get("attempt", {}).get("Exam_Id")
        or raw_payload.get("attempt", {}).get("ExamId")
        or raw_payload.get("summary", {}).get("ID")
    )
    if (
        default_candidate_id
        and raw_payload.get("attempt")
        and (not requested_candidate_id or default_candidate_id == requested_candidate_id)
        and (not requested_exam_id or default_attempt_exam_id == requested_exam_id)
    ):
        attempts_by_candidate.setdefault(default_candidate_id, []).append(raw_payload["attempt"])

    candidate_records = raw_payload.get("candidate_records", {})
    candidate_analyses: dict[str, dict[str, Any]] = {}
    all_attempt_analyses: list[dict[str, Any]] = []

    for candidate_id in sorted(attempts_by_candidate):
        record = candidate_records.get(str(candidate_id), {})
        candidate_details = record.get("details") or (
            raw_payload.get("candidate", {}) if candidate_id == default_candidate_id else {}
        )
        candidate_profile = record.get("profile") or (
            raw_payload.get("candidate_profile", {}) if candidate_id == default_candidate_id else {}
        )
        attempt_payloads = []

        for attempt_index, attempt_record in enumerate(attempts_by_candidate[candidate_id], start=1):
            candidate_raw_payload = {
                "candidate": candidate_details,
                "candidate_profile": candidate_profile,
                "summary": attempt_record,
                "attempt": attempt_record,
                "metadata": _metadata_from_attempt(
                    attempt_record,
                    {
                        **raw_payload.get("metadata", {}),
                        **raw_payload.get("summary", {}),
                    },
                ),
                "course_list": raw_payload.get("course_list", []),
                "all_candidate_attempts": raw_payload.get("all_candidate_attempts", []),
                "raw_apis": {
                    **record.get("raw_apis", {}),
                    "source_attempt": {
                        "candidate_id": candidate_id,
                        "attempt_index": attempt_index,
                        "body": attempt_record,
                    },
                },
            }
            try:
                attempt_payload = await build_dashboard_payload(candidate_raw_payload)
            except ValueError as exc:
                if "Exam Attempt Answer API did not return" in str(exc):
                    continue
                raise
            attempt_payload["attempt_id"] = _safe_int(
                attempt_record.get("AttemptId") or attempt_record.get("Attempt_Id") or attempt_record.get("AttemptID")
            )
            attempt_payload["attempt_source"] = (
                "all_candidate_attempts"
                if attempt_record in raw_payload.get("all_candidate_attempts", [])
                else "configured_candidate_attempt"
            )
            attempt_payloads.append(attempt_payload)
            all_attempt_analyses.append(attempt_payload)

        if not attempt_payloads:
            continue

        candidate_analyses[str(candidate_id)] = _build_candidate_analysis_entry(
            candidate_id=candidate_id,
            attempt_payloads=attempt_payloads,
        )

    ranked_candidates = _rank_candidate_entries(candidate_analyses)
    _apply_canonical_rankings(candidate_analyses, ranked_candidates)
    _validate_ranking_consistency(candidate_analyses, ranked_candidates)
    generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return {
        "generated_at": generated_at,
        "analysis_scope": "multi_candidate",
        "candidate_count": len(candidate_analyses),
        "attempt_count": len(all_attempt_analyses),
        "request_context": request_context,
        "candidates": list(candidate_analyses.values()),
        "candidate_analyses": candidate_analyses,
        "ranked_candidates": ranked_candidates,
        "top_performer": ranked_candidates[0] if ranked_candidates else {},
        "attempt_analyses": all_attempt_analyses,
        "raw_apis": raw_payload.get("raw_apis", {}),
    }


def _candidate_id_from_record(record: dict[str, Any]) -> int:
    return _safe_int(
        record.get("CandidateId")
        or record.get("Candidate_Id")
        or record.get("candidateId")
        or record.get("candidateid")
    )


def _metadata_from_attempt(attempt_record: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        **fallback,
        "Exam_Id": attempt_record.get("Exam_Id") or attempt_record.get("ExamId") or fallback.get("ID") or fallback.get("Exam_Id"),
        "Exam_Name": attempt_record.get("Exam_Name") or attempt_record.get("ExamName") or fallback.get("Exam_Name"),
        "Exam_Duration": attempt_record.get("Exam_Duration") or attempt_record.get("ExamDuration") or fallback.get("Exam_Duration"),
        "Evaluation_Type_Name": (
            attempt_record.get("Evaluation_Type_Name")
            or attempt_record.get("EvaluationTypeName")
            or fallback.get("Evaluation_Type_Name")
        ),
    }


def _build_candidate_analysis_entry(
    *,
    candidate_id: int,
    attempt_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    primary_attempt = max(
        attempt_payloads,
        key=lambda item: (
            item.get("summary", {}).get("overall_score_percent", 0),
            item.get("summary", {}).get("accuracy", 0),
        ),
    )
    summary_rows = []
    for payload in attempt_payloads:
        summary = payload.get("summary", {})
        ranking_row = payload.get("ranking_summary", {})
        summary_rows.append(
            {
                "exam_id": payload.get("exam", {}).get("exam_id"),
                "exam_name": payload.get("exam", {}).get("name"),
                "attempt_id": payload.get("attempt_id"),
                "rank": ranking_row.get("current_candidate_rank"),
                "accuracy": summary.get("raw_accuracy", summary.get("accuracy", 0)),
                "raw_accuracy": summary.get("raw_accuracy", summary.get("accuracy", 0)),
                "weighted_accuracy": summary.get("weighted_accuracy", summary.get("overall_score_percent", 0)),
                "marks_percent": summary.get("marks_percent", summary.get("overall_score_percent", 0)),
                "obtained_marks": summary.get("obtained_marks", 0),
                "total_marks": summary.get("total_marks", 0),
                "time_taken_seconds": summary.get("time_taken_seconds", 0),
                "attempted_questions": summary.get("attempted_questions", 0),
                "total_questions": summary.get("total_questions", 0),
            }
        )

    student = primary_attempt.get("student", {})
    avg_accuracy = round(
        sum(float(item.get("accuracy") or 0) for item in summary_rows) / len(summary_rows),
        2,
    )
    avg_marks = round(
        sum(float(item.get("marks_percent") or 0) for item in summary_rows) / len(summary_rows),
        2,
    )
    return {
        "candidate_id": candidate_id,
        "candidate_name": student.get("name") or f"Candidate {candidate_id}",
        "profile": student,
        "summary": {
            "attempts": len(attempt_payloads),
            "average_accuracy": avg_accuracy,
            "average_marks_percent": avg_marks,
            "best_exam": primary_attempt.get("exam", {}).get("name"),
            "best_marks_percent": primary_attempt.get("summary", {}).get("overall_score_percent", 0),
        },
        "attempt_summaries": summary_rows,
        "primary_attempt": primary_attempt,
        "attempts": attempt_payloads,
    }


def _rank_candidate_entries(candidate_analyses: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for entry in candidate_analyses.values():
        primary = entry.get("primary_attempt", {})
        summary = entry.get("summary", {})
        primary_summary = primary.get("summary", {})
        rows.append(
            {
                "candidate_id": entry.get("candidate_id"),
                "candidate_name": entry.get("candidate_name"),
                "attempts": summary.get("attempts", 0),
                "accuracy": summary.get("average_accuracy", 0),
                "raw_accuracy": summary.get("average_accuracy", 0),
                "weighted_accuracy": summary.get("average_marks_percent", 0),
                "marks_percent": summary.get("average_marks_percent", 0),
                "best_marks_percent": summary.get("best_marks_percent", 0),
                "best_exam": summary.get("best_exam"),
                "speed_score": primary.get("ranking_summary", {}).get("speed_score")
                or primary.get("top_performer", {}).get("speed_score")
                or 0,
                "composite_score": round(
                    (float(summary.get("average_marks_percent") or 0) * 0.55)
                    + (float(summary.get("average_accuracy") or 0) * 0.45),
                    2,
                ),
                "time_taken_seconds": sum(
                    int(item.get("time_taken_seconds") or 0)
                    for item in entry.get("attempt_summaries", [])
                ),
                "attempted_questions": sum(
                    int(item.get("attempted_questions") or 0)
                    for item in entry.get("attempt_summaries", [])
                ),
                "total_questions": sum(
                    int(item.get("total_questions") or 0)
                    for item in entry.get("attempt_summaries", [])
                ),
                "obtained_marks": sum(
                    float(item.get("obtained_marks") or 0)
                    for item in entry.get("attempt_summaries", [])
                ),
                "total_marks": sum(
                    float(item.get("total_marks") or 0)
                    for item in entry.get("attempt_summaries", [])
                ),
                "average_time_per_question_seconds": primary_summary.get(
                    "average_time_per_question_seconds",
                    0,
                ),
            }
        )

    rows.sort(
        key=lambda item: (
            item["composite_score"],
            item["best_marks_percent"],
            item["accuracy"],
        ),
        reverse=True,
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _apply_canonical_rankings(
    candidate_analyses: dict[str, dict[str, Any]],
    ranked_candidates: list[dict[str, Any]],
) -> None:
    total_candidates = len(ranked_candidates)
    leader_score = float(ranked_candidates[0].get("composite_score") or 0) if ranked_candidates else 0.0
    ranking_by_candidate = {
        int(row.get("candidate_id") or 0): row
        for row in ranked_candidates
        if int(row.get("candidate_id") or 0)
    }

    for candidate_key, entry in candidate_analyses.items():
        candidate_id = int(entry.get("candidate_id") or candidate_key or 0)
        ranking = ranking_by_candidate.get(candidate_id)
        if ranking is None:
            continue
        rank = int(ranking.get("rank") or 0)
        entry["rank"] = rank
        entry["ranking"] = ranking
        entry.setdefault("summary", {})["rank"] = rank
        entry["summary"]["total_candidates"] = total_candidates
        entry["summary"]["leader_gap_score"] = round(
            max(0.0, leader_score - float(ranking.get("composite_score") or 0)),
            2,
        )

        for summary in entry.get("attempt_summaries", []):
            summary["rank"] = rank
            summary["total_candidates"] = total_candidates

        for attempt in entry.get("attempts", []):
            attempt.pop("rankings", None)
            attempt.pop("top_performer", None)
            attempt["ranking_summary"] = {
                "current_candidate_rank": rank,
                "leaderboard_rank": rank,
                "attempt_rank": rank,
                "total_candidates": total_candidates,
                "ranking_source": "canonical_candidate_ranking",
                "leader_gap_score": entry["summary"]["leader_gap_score"],
            }


def _validate_ranking_consistency(
    candidate_analyses: dict[str, dict[str, Any]],
    ranked_candidates: list[dict[str, Any]],
) -> None:
    total_candidates = len(ranked_candidates)
    if total_candidates != len(candidate_analyses):
        raise ValueError(
            "Ranking validation failed: ranked candidate count does not match candidate_analyses count."
        )

    ranks = [int(row.get("rank") or 0) for row in ranked_candidates]
    if sorted(ranks) != list(range(1, total_candidates + 1)):
        raise ValueError("Ranking validation failed: leaderboard ranks are not contiguous.")

    ranking_by_candidate = {
        str(row.get("candidate_id")): row
        for row in ranked_candidates
    }
    for candidate_key, entry in candidate_analyses.items():
        ranking = ranking_by_candidate.get(candidate_key)
        if ranking is None:
            raise ValueError(f"Ranking validation failed: candidate {candidate_key} is missing from leaderboard.")
        expected_rank = int(ranking.get("rank") or 0)
        observed_ranks = {
            int(entry.get("rank") or 0),
            int(entry.get("summary", {}).get("rank") or 0),
        }
        for summary in entry.get("attempt_summaries", []):
            observed_ranks.add(int(summary.get("rank") or 0))
            if int(summary.get("total_candidates") or 0) != total_candidates:
                raise ValueError(
                    f"Ranking validation failed: candidate {candidate_key} attempt summary total_candidates mismatch."
                )
        for attempt in entry.get("attempts", []):
            ranking_summary = attempt.get("ranking_summary", {})
            observed_ranks.update(
                {
                    int(ranking_summary.get("current_candidate_rank") or 0),
                    int(ranking_summary.get("leaderboard_rank") or 0),
                    int(ranking_summary.get("attempt_rank") or 0),
                }
            )
            if int(ranking_summary.get("total_candidates") or 0) != total_candidates:
                raise ValueError(
                    f"Ranking validation failed: candidate {candidate_key} attempt total_candidates mismatch."
                )
        if observed_ranks != {expected_rank}:
            raise ValueError(
                f"Ranking validation failed: candidate {candidate_key} has rank mismatch {sorted(observed_ranks)} vs {expected_rank}."
            )


def _seconds_to_display(total_seconds: int) -> str:
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds}s"


def _ai_label_or_none(value: Any) -> str | None:
    label = str(value or "").strip()
    if not label or label.lower() == DEFAULT_LABEL.lower():
        return None
    return label
