from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.config import DOMAIN_LABELS
from app.services.recommendation import RecommendationService


DOMAIN_KEYWORDS = {
    "Backend": ["api", "server", "database", "sql", "fastapi", "flask", "django"],
    "Frontend": ["html", "css", "javascript", "react", "vue", "dom", "ui"],
    "ML": ["model", "dataset", "training", "regression", "classification", "numpy"],
    "Security": ["auth", "encryption", "xss", "csrf", "vulnerability", "token"],
    "DevOps": ["docker", "kubernetes", "ci", "cd", "deployment", "pipeline", "linux"],
}


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


def _normalize_domain(question: dict[str, Any], index: int) -> tuple[str, str, str]:
    text_parts = [str(question.get("Question_Text", ""))]
    options = question.get("Options", [])
    text_parts.extend(str(option.get("Option_Text", "")) for option in options)
    corpus = " ".join(text_parts).lower()

    for domain, keywords in DOMAIN_KEYWORDS.items():
        for keyword in keywords:
            if keyword in corpus:
                return domain, keyword.title(), "keyword"

    fallback_domain = DOMAIN_LABELS[index % len(DOMAIN_LABELS)]
    return fallback_domain, "General Aptitude", "fallback"


def _extract_answers(question: dict[str, Any]) -> tuple[str, str]:
    selected_option = next(
        (
            option.get("Candidate_Selected_Option_Text", "")
            for option in question.get("Options", [])
            if option.get("Is_Selected_By_Candidate")
        ),
        "",
    )
    correct_option = next(
        (
            option.get("Option_Text", "")
            for option in question.get("Options", [])
            if option.get("Is_Correct_Option")
        ),
        "",
    )
    return str(selected_option), str(correct_option)


def _is_correct(question: dict[str, Any]) -> bool:
    options = question.get("Options", [])
    return any(
        option.get("Is_Correct_Option") and option.get("Is_Selected_By_Candidate")
        for option in options
    )


async def build_dashboard_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
    attempt = raw_payload.get("attempt", {})
    if not attempt:
        raise ValueError("Exam Attempt Answer API did not return a usable attempt payload")

    questions = attempt.get("Questions", [])
    started_on = _safe_datetime(attempt.get("StartedOn"))
    submitted_on = _safe_datetime(attempt.get("SubmittedOn"))
    total_time_seconds = 0
    if started_on and submitted_on:
        total_time_seconds = int((submitted_on - started_on).total_seconds())

    attempted_questions = sum(1 for question in questions if question.get("IsAnswered"))
    total_questions = len(questions)
    equal_time = round(total_time_seconds / attempted_questions, 2) if attempted_questions else 0.0

    domain_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    question_rows = []

    for index, question in enumerate(questions):
        selected_answer, correct_answer = _extract_answers(question)
        is_answered = bool(question.get("IsAnswered"))
        is_correct = _is_correct(question)
        domain, topic, mapping_source = _normalize_domain(question, index)
        full_marks = float(question.get("Full_Marks") or 0)
        marks_obtained = float(question.get("EvaluatedMarks") or (full_marks if is_correct else 0))
        time_spent = equal_time if is_answered else 0.0
        status = "Correct" if is_correct else ("Incorrect" if is_answered else "Skipped")

        row = {
            "question_id": int(question.get("Question_Id", 0)),
            "question_text": str(question.get("Question_Text", "")),
            "question_type": str(question.get("Question_Type_Name", "Unknown")),
            "domain": domain,
            "topic": topic,
            "difficulty": str(
                raw_payload.get("metadata", {}).get("Exam_Level_Name")
                or raw_payload.get("summary", {}).get("Exam_Level_Name")
                or "Intermediate"
            ),
            "mapping_source": mapping_source,
            "status": status,
            "is_answered": is_answered,
            "is_correct": is_correct,
            "marks_obtained": marks_obtained,
            "full_marks": full_marks,
            "negative_marks": float(question.get("Negative_Marks") or 0),
            "time_spent_seconds": time_spent,
            "selected_answer": selected_answer,
            "correct_answer": correct_answer,
        }
        question_rows.append(row)
        domain_buckets[domain].append(row)

    obtained_marks = round(sum(row["marks_obtained"] for row in question_rows), 2)
    total_marks = round(sum(row["full_marks"] for row in question_rows), 2)
    correct_answers = sum(1 for row in question_rows if row["is_correct"])
    incorrect_answers = sum(1 for row in question_rows if row["status"] == "Incorrect")
    overall_accuracy = round((correct_answers / attempted_questions) * 100, 2) if attempted_questions else 0.0
    average_time = round((total_time_seconds / attempted_questions), 2) if attempted_questions else 0.0

    domain_rows = []
    for domain in DOMAIN_LABELS:
        rows = domain_buckets.get(domain, [])
        domain_attempted = sum(1 for row in rows if row["is_answered"])
        domain_correct = sum(1 for row in rows if row["is_correct"])
        domain_incorrect = sum(1 for row in rows if row["status"] == "Incorrect")
        domain_total_marks = round(sum(row["full_marks"] for row in rows), 2)
        domain_marks = round(sum(row["marks_obtained"] for row in rows), 2)
        domain_accuracy = round((domain_correct / len(rows)) * 100, 2) if rows else 0.0
        weak_topic_candidates = [row["topic"] for row in rows if row["status"] != "Correct"]
        topic_counter = Counter(weak_topic_candidates)

        domain_rows.append(
            {
                "domain": domain,
                "total_questions": len(rows),
                "attempted_questions": domain_attempted,
                "correct_answers": domain_correct,
                "incorrect_answers": domain_incorrect,
                "marks_obtained": domain_marks,
                "total_marks": domain_total_marks,
                "accuracy": domain_accuracy,
                "average_time_seconds": round(
                    sum(row["time_spent_seconds"] for row in rows) / domain_attempted, 2
                )
                if domain_attempted
                else 0.0,
                "classification": _classify_strength(domain_accuracy),
                "weak_topics": [topic for topic, _ in topic_counter.most_common(3)],
            }
        )

    ranked_domains = sorted(domain_rows, key=lambda row: row["accuracy"], reverse=True)
    strengths = [row["domain"] for row in ranked_domains if row["classification"] == "Strong"][:3]
    if not strengths and ranked_domains:
        strengths = [ranked_domains[0]["domain"]]

    weaknesses = [
        row["domain"] for row in sorted(domain_rows, key=lambda row: row["accuracy"]) if row["total_questions"]
    ][:3]
    if not weaknesses:
        weaknesses = ["General Practice"]

    metadata = raw_payload.get("metadata", {})
    summary = raw_payload.get("summary", {})
    candidate = raw_payload.get("candidate", {})
    generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    payload = {
        "student": {
            "candidate_id": int(candidate.get("candidateid") or attempt.get("Candidate_Id") or 0),
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
        },
        "exam": {
            "exam_id": int(attempt.get("Exam_Id") or summary.get("ID") or 0),
            "name": metadata.get("Exam_Name") or attempt.get("Exam_Name") or summary.get("Exam_Name") or "Assessment",
            "duration_minutes": int(
                metadata.get("Exam_Duration")
                or summary.get("Exam_Duration")
                or 0
            ),
            "difficulty": metadata.get("Exam_Level_Name") or summary.get("Exam_Level_Name") or "Intermediate",
            "total_questions": total_questions,
            "evaluation_type": summary.get("Evaluation_Type_Name", "Unknown"),
        },
        "summary": {
            "overall_score_percent": round((obtained_marks / total_marks) * 100, 2) if total_marks else 0.0,
            "obtained_marks": obtained_marks,
            "total_marks": total_marks,
            "correct_answers": correct_answers,
            "incorrect_answers": incorrect_answers,
            "attempted_questions": attempted_questions,
            "total_questions": total_questions,
            "accuracy": overall_accuracy,
            "time_taken_seconds": total_time_seconds,
            "time_taken_display": _seconds_to_display(total_time_seconds),
            "average_time_per_question_seconds": average_time,
            "correct_vs_incorrect_ratio": round(
                correct_answers / incorrect_answers, 2
            )
            if incorrect_answers
            else float(correct_answers),
        },
        "domains": domain_rows,
        "questions": question_rows,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendations": [],
        "raw_apis": raw_payload.get("raw_apis", {}),
        "generated_at": generated_at,
    }

    recommendation_service = RecommendationService()
    recommendation_result = await recommendation_service.generate(payload)
    payload["recommendations"] = recommendation_result["recommendations"]
    payload["raw_apis"]["analysis_api"] = recommendation_result["raw_api"]
    return payload


def _seconds_to_display(total_seconds: int) -> str:
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds}s"
