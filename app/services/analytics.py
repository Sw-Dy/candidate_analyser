from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.config import DOMAIN_LABELS
from app.services.recommendation import RecommendationService
from app.services.skill_intelligence import SkillIntelligenceService


TOPIC_KEYWORDS = [
    ("Backend", "HTTP 404", ["status code", "page not found", "404"]),
    ("Backend", "URL Flow", ["type a url", "url in the browser", "url in browser", "dns", "http request"]),
    ("Backend", "REST", ["rest api", "restful", "http methods", "get post put delete"]),
    ("Backend", "API", ["api"]),
    ("Backend", ".NET", ["c# framework", "asp.net", ".net core", "dot net"]),
    ("Backend", "NoSQL", ["nosql", "mongodb", "mongo db", "mongo"]),
    ("Backend", "SQL", ["sql", "query language"]),
    ("Backend", "Database", ["database", "dbms", "table"]),
    ("Backend", "Django", ["django"]),
    ("Backend", "Server", ["server", "backend", "fastapi", "flask"]),
    ("Frontend", "HTML/CSS", ["html", "css"]),
    ("Frontend", "JavaScript", ["javascript", "dom"]),
    ("Frontend", "React", ["react"]),
    ("Frontend", "UI", ["frontend", "ui", "vue"]),
    ("ML", "ML Models", ["model", "training", "regression", "classification", "numpy"]),
    ("ML", "Datasets", ["dataset"]),
    ("Security", "Authentication", ["auth", "token"]),
    ("Security", "Web Security", ["encryption", "xss", "csrf", "vulnerability"]),
    ("DevOps", "Containers", ["docker", "kubernetes"]),
    ("DevOps", "Deployment Pipelines", ["ci", "cd", "deployment", "pipeline", "linux"]),
]


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


def _normalize_domain(question: dict[str, Any], index: int) -> tuple[str, str, str]:
    text_parts = [str(question.get("Question_Text", ""))]
    options = question.get("Options", [])
    text_parts.extend(str(option.get("Option_Text", "")) for option in options)
    corpus = re.sub(r"\s+", " ", " ".join(text_parts).lower()).strip()

    for domain, topic, keywords in TOPIC_KEYWORDS:
        for keyword in keywords:
            if keyword in corpus:
                return domain, topic, "keyword"

    fallback_domain = DOMAIN_LABELS[index % len(DOMAIN_LABELS)]
    return fallback_domain, _fallback_topic_label(corpus), "fallback"


def _fallback_topic_label(corpus: str) -> str:
    if any(word in corpus for word in ["aptitude", "logic", "reasoning", "pattern"]):
        return "Reasoning"
    if any(word in corpus for word in ["write", "explain", "describe"]):
        return "Concept Explanation"
    return "General Concepts"


def _build_topic_strengths_and_weaknesses(question_rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    topic_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0, "wrong": 0})

    for row in question_rows:
        topic = str(row.get("topic") or row.get("domain") or "General Concepts").strip()
        if not topic:
            topic = "General Concepts"
        stats = topic_stats[topic]
        stats["total"] += 1
        if row.get("is_correct"):
            stats["correct"] += 1
        else:
            stats["wrong"] += 1

    strengths = []
    weaknesses = []
    for topic, stats in topic_stats.items():
        if stats["correct"] > stats["wrong"]:
            strengths.append(
                {
                    "topic": topic,
                    "label": f"{topic} ({stats['correct']}/{stats['total']} correct)",
                    "total": stats["total"],
                    "score": stats["correct"] / stats["total"],
                }
            )
        elif stats["wrong"] > stats["correct"]:
            weaknesses.append(
                {
                    "topic": topic,
                    "label": f"{topic} ({stats['wrong']}/{stats['total']} wrong)",
                    "total": stats["total"],
                    "score": stats["wrong"] / stats["total"],
                }
            )

    strengths.sort(key=lambda item: (item["score"], item["total"], item["topic"]), reverse=True)
    weaknesses.sort(key=lambda item: (item["score"], item["total"], item["topic"]), reverse=True)
    return [item["label"] for item in strengths], [item["label"] for item in weaknesses]


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


def _is_correct(question: dict[str, Any]) -> bool:
    options = question.get("Options", [])
    option_match = any(
        (option.get("Is_Correct_Option") or option.get("IsCorrectOption"))
        and (option.get("Is_Selected_By_Candidate") or option.get("IsSelectedByCandidate"))
        for option in options
    )
    if option_match:
        return True

    evaluated_marks = _safe_float(question.get("EvaluatedMarks") or question.get("Evaluated_Marks"))
    return evaluated_marks > 0


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
    all_skill_labels: list[str],
    average_time_seconds: float,
    source: str,
) -> dict[str, Any]:
    skill_scores: dict[str, list[float]] = defaultdict(list)
    skill_question_ids: dict[str, set[int]] = defaultdict(set)

    for row in question_rows:
        marks_percent = (row["marks_obtained"] / row["full_marks"] * 100) if row["full_marks"] else 0.0
        accuracy_score = 100.0 if row["is_correct"] else (35.0 if row["is_answered"] else 0.0)
        speed_score = _question_speed_score(row["time_spent_seconds"], average_time_seconds)
        question_score = round((marks_percent * 0.45) + (accuracy_score * 0.4) + (speed_score * 0.15), 2)

        skills = [row.get("primary_skill")] + list(row.get("supporting_skills", []))
        deduped_skills = [skill for skill in dict.fromkeys(skills) if skill]
        for index, skill in enumerate(deduped_skills):
            weight = 1.0 if index == 0 else 0.6
            skill_scores[skill].append(question_score * weight)
            skill_question_ids[skill].add(row["question_id"])

    labels = []
    scores = []
    details = []
    for skill in dict.fromkeys(all_skill_labels):
        values = skill_scores.get(skill, [])
        score = round(sum(values) / len(values), 2) if values else 0.0
        labels.append(skill)
        scores.append(score)
        details.append(
            {
                "skill": skill,
                "score": score,
                "question_count": len(skill_question_ids.get(skill, set())),
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
    return round((correct / attempted) * 100, 2) if attempted else 0.0


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
        obtained_marks = _safe_float(
            record.get("ObtainedMarks") or record.get("obtained_marks") or record.get("Score")
        )
        total_marks = _safe_float(
            record.get("TotalMarks") or record.get("total_marks") or current_payload["summary"]["total_marks"]
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
            (row["marks_percent"] * 0.45) + (row["accuracy"] * 0.35) + (row["speed_score"] * 0.20),
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

    domain_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    question_rows = []

    for index, question in enumerate(questions):
        selected_answer, correct_answer = _extract_answers(question)
        is_answered = bool(question.get("IsAnswered"))
        if not is_answered:
            is_answered = bool(question.get("is_answered"))
        is_correct = _is_correct(question)
        domain, topic, mapping_source = _normalize_domain(question, index)
        full_marks = float(question.get("Full_Marks") or 0)
        marks_obtained = float(question.get("EvaluatedMarks") or (full_marks if is_correct else 0))
        time_spent = equal_time if is_answered else 0.0
        status = "Correct" if is_correct else ("Incorrect" if is_answered else "Skipped")

        row = {
            "question_id": int(question.get("Question_Id") or question.get("QuestionId") or 0),
            "question_text": str(question.get("Question_Text", "")),
            "question_type": str(question.get("Question_Type_Name") or question.get("QuestionTypeName") or "Unknown"),
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
            "primary_skill": None,
            "supporting_skills": [],
            "difficulty_label": "Intermediate",
            "difficulty_rating": 3,
        }
        question_rows.append(row)
        domain_buckets[domain].append(row)

    summary = raw_payload.get("summary", {})
    obtained_marks = round(
        _safe_float(summary.get("ObtainedMarks") or summary.get("obtained_marks"))
        or sum(row["marks_obtained"] for row in question_rows),
        2,
    )
    total_marks = round(
        _safe_float(summary.get("TotalMarks") or summary.get("total_marks"))
        or sum(row["full_marks"] for row in question_rows),
        2,
    )
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
                "classification": _classify_strength(domain_accuracy) if rows else "No Data",
                "weak_topics": [topic for topic, _ in topic_counter.most_common(3)],
            }
        )

    strengths, weaknesses = _build_topic_strengths_and_weaknesses(question_rows)

    metadata = raw_payload.get("metadata", {})
    candidate = raw_payload.get("candidate", {})
    candidate_profile = _build_candidate_profile(raw_payload.get("candidate_profile", {}))
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
            "applied_position": candidate_profile.get("position", "Not provided"),
            "languages": candidate_profile.get("languages", []),
            "computer_proficiency": candidate_profile.get("computer_proficiency", ""),
        },
        "exam": {
            "exam_id": int(attempt.get("Exam_Id") or attempt.get("ExamId") or summary.get("ID") or summary.get("ExamId") or 0),
            "name": metadata.get("Exam_Name") or attempt.get("Exam_Name") or attempt.get("ExamName") or summary.get("Exam_Name") or summary.get("ExamName") or "Assessment",
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
        "skill_radar": {"labels": [], "scores": [], "details": [], "source": "pending"},
        "rankings": [],
        "top_performer": {},
        "ranking_summary": {},
        "recommendations": [],
        "recommended_courses": [],
        "raw_apis": raw_payload.get("raw_apis", {}),
        "generated_at": generated_at,
    }

    skill_service = SkillIntelligenceService()
    skill_result = await skill_service.enrich(
        candidate_profile=candidate_profile,
        exam=payload["exam"],
        questions=question_rows,
    )
    question_intelligence = {
        item["question_id"]: item
        for item in skill_result.get("questions", [])
        if item.get("question_id")
    }
    all_skill_labels = skill_result.get("skills", [])
    for row in payload["questions"]:
        intelligence = question_intelligence.get(row["question_id"], {})
        if intelligence.get("domain"):
            row["domain"] = intelligence["domain"]
        if intelligence.get("topic"):
            row["topic"] = intelligence["topic"]
        row["primary_skill"] = intelligence.get("primary_skill") or row["domain"]
        row["supporting_skills"] = intelligence.get("supporting_skills", [])
        row["difficulty_label"] = intelligence.get("difficulty_label", row["difficulty"])
        row["difficulty_rating"] = intelligence.get("difficulty_rating", 3)

    payload["strengths"], payload["weaknesses"] = _build_topic_strengths_and_weaknesses(payload["questions"])

    payload["skill_radar"] = _build_skill_radar(
        question_rows=payload["questions"],
        all_skill_labels=all_skill_labels or DOMAIN_LABELS,
        average_time_seconds=average_time,
        source=skill_result.get("source", "fallback"),
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
    return payload


async def build_all_candidate_analysis(raw_payload: dict[str, Any]) -> dict[str, Any]:
    attempts_by_candidate: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in raw_payload.get("all_candidate_attempts", []):
        candidate_id = _candidate_id_from_record(record)
        if candidate_id:
            attempts_by_candidate[candidate_id].append(record)

    default_candidate_id = _safe_int(raw_payload.get("candidate", {}).get("candidateid"))
    if default_candidate_id and raw_payload.get("attempt"):
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
                "metadata": _metadata_from_attempt(attempt_record, raw_payload.get("metadata", {})),
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
            except ValueError:
                continue
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
    generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return {
        "generated_at": generated_at,
        "analysis_scope": "multi_candidate",
        "candidate_count": len(candidate_analyses),
        "attempt_count": len(all_attempt_analyses),
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
        "Exam_Id": attempt_record.get("Exam_Id") or attempt_record.get("ExamId") or fallback.get("Exam_Id"),
        "Exam_Name": attempt_record.get("Exam_Name") or attempt_record.get("ExamName") or fallback.get("Exam_Name"),
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
                "accuracy": summary.get("accuracy", 0),
                "marks_percent": summary.get("overall_score_percent", 0),
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


def _seconds_to_display(total_seconds: int) -> str:
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds}s"
