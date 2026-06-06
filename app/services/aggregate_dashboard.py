from __future__ import annotations

from statistics import mean
from typing import Any


def build_aggregate_dashboard(
    analysis_payload: dict[str, Any],
    corpus_payload: dict[str, Any],
    *,
    source: str,
    selected_candidate_id: int | None = None,
) -> dict[str, Any]:
    if analysis_payload.get("analysis_scope") == "multi_candidate":
        return _build_multi_candidate_dashboard(
            analysis_payload,
            source=source,
            selected_candidate_id=selected_candidate_id,
        )

    rankings = list(analysis_payload.get("rankings", []))
    student = analysis_payload.get("student", {})
    exam = analysis_payload.get("exam", {})
    top_performer = analysis_payload.get("top_performer", {}) or (rankings[0] if rankings else {})
    current_candidate_id = int(student.get("candidate_id") or 0)

    if not rankings:
        rankings = [
            {
                "candidate_id": current_candidate_id,
                "candidate_name": student.get("name", "Unknown Candidate"),
                "accuracy": analysis_payload.get("summary", {}).get("accuracy", 0),
                "marks_percent": analysis_payload.get("summary", {}).get("overall_score_percent", 0),
                "composite_score": 0,
                "speed_score": 0,
                "rank": 1,
                "average_time_per_question_seconds": analysis_payload.get("summary", {}).get(
                    "average_time_per_question_seconds", 0
                ),
                "time_taken_seconds": analysis_payload.get("summary", {}).get("time_taken_seconds", 0),
                "obtained_marks": analysis_payload.get("summary", {}).get("obtained_marks", 0),
                "total_marks": analysis_payload.get("summary", {}).get("total_marks", 0),
                "total_questions": analysis_payload.get("summary", {}).get("total_questions", 0),
                "attempted_questions": analysis_payload.get("summary", {}).get("attempted_questions", 0),
            }
        ]
        top_performer = rankings[0]

    candidate_summaries = [_build_candidate_summary(row, current_candidate_id) for row in rankings]
    top_performer_candidate_id = int(top_performer.get("candidate_id") or current_candidate_id)
    selected_id = selected_candidate_id or top_performer_candidate_id
    selected_row = next(
        (row for row in rankings if int(row.get("candidate_id") or 0) == int(selected_id)),
        top_performer,
    )

    selected_candidate = _build_selected_candidate_detail(
        selected_row=selected_row,
        analysis_payload=analysis_payload,
        corpus_payload=corpus_payload,
        current_candidate_id=current_candidate_id,
    )
    top_performer_analysis = _build_top_performer_analysis(
        top_performer=top_performer,
        analysis_payload=analysis_payload,
        current_candidate_id=current_candidate_id,
    )
    aggregate_analysis = _build_aggregate_analysis(
        rankings=rankings,
        analysis_payload=analysis_payload,
        exam_name=str(exam.get("name") or "Assessment"),
    )

    return {
        "generated_at": analysis_payload.get("generated_at"),
        "source": source,
        "exam": exam,
        "overview": {
            "total_candidates": len(rankings),
            "top_performer_name": top_performer.get("candidate_name", "Unknown Candidate"),
            "current_candidate_id": current_candidate_id,
            "current_candidate_name": student.get("name", "Unknown Candidate"),
        },
        "aggregate_analysis": aggregate_analysis,
        "top_performer_analysis": top_performer_analysis,
        "ranked_candidates": candidate_summaries,
        "selected_candidate": selected_candidate,
        "charts": {
            "ranking_labels": [item["candidate_name"] for item in candidate_summaries[:10]],
            "composite_scores": [item["composite_score"] for item in candidate_summaries[:10]],
            "accuracy_scores": [item["accuracy"] for item in candidate_summaries[:10]],
        },
    }


def _build_multi_candidate_dashboard(
    analysis_payload: dict[str, Any],
    *,
    source: str,
    selected_candidate_id: int | None,
) -> dict[str, Any]:
    ranked_candidates = list(analysis_payload.get("ranked_candidates", []))
    candidate_analyses = analysis_payload.get("candidate_analyses", {})
    top_performer = analysis_payload.get("top_performer", {}) or (ranked_candidates[0] if ranked_candidates else {})
    selected_id = selected_candidate_id or top_performer.get("candidate_id")
    selected_entry = candidate_analyses.get(str(selected_id)) or next(iter(candidate_analyses.values()), {})
    selected_candidate = _build_multi_selected_candidate_detail(selected_entry, ranked_candidates)
    aggregate_analysis = _build_multi_aggregate_analysis(
        ranked_candidates=ranked_candidates,
        attempt_count=int(analysis_payload.get("attempt_count") or 0),
    )
    top_performer_analysis = _build_multi_top_performer_analysis(top_performer, selected_entry)

    return {
        "generated_at": analysis_payload.get("generated_at"),
        "source": source,
        "exam": {"name": "All available candidate attempts", "exam_id": 0},
        "overview": {
            "total_candidates": len(ranked_candidates),
            "top_performer_name": top_performer.get("candidate_name", "Unknown Candidate"),
            "current_candidate_id": selected_candidate.get("candidate_id", 0),
            "current_candidate_name": selected_candidate.get("candidate_name", "Unknown Candidate"),
        },
        "aggregate_analysis": aggregate_analysis,
        "top_performer_analysis": top_performer_analysis,
        "ranked_candidates": [
            {
                **item,
                "has_full_analysis": True,
                "is_current_candidate": item.get("candidate_id") == selected_candidate.get("candidate_id"),
            }
            for item in ranked_candidates
        ],
        "selected_candidate": selected_candidate,
        "charts": {
            "ranking_labels": [item.get("candidate_name", "Unknown") for item in ranked_candidates[:10]],
            "composite_scores": [item.get("composite_score", 0) for item in ranked_candidates[:10]],
            "accuracy_scores": [item.get("accuracy", 0) for item in ranked_candidates[:10]],
        },
    }


def _build_multi_selected_candidate_detail(
    selected_entry: dict[str, Any],
    ranked_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = selected_entry.get("primary_attempt", {})
    candidate_id = int(selected_entry.get("candidate_id") or 0)
    ranked_row = next(
        (item for item in ranked_candidates if int(item.get("candidate_id") or 0) == candidate_id),
        {},
    )
    profile = selected_entry.get("profile", {})
    questions = []
    for attempt in selected_entry.get("attempts", []):
        exam = attempt.get("exam", {})
        for question in attempt.get("questions", []):
            questions.append(
                {
                    **question,
                    "exam_id": exam.get("exam_id"),
                    "exam_name": exam.get("name"),
                }
            )

    return {
        "candidate_id": candidate_id,
        "candidate_name": selected_entry.get("candidate_name", f"Candidate {candidate_id}"),
        "rank": ranked_row.get("rank", 0),
        "analysis_scope": "full",
        "summary": {
            "accuracy": ranked_row.get("accuracy", 0),
            "marks_percent": ranked_row.get("marks_percent", 0),
            "composite_score": ranked_row.get("composite_score", 0),
            "speed_score": ranked_row.get("speed_score", 0),
            "time_taken_seconds": ranked_row.get("time_taken_seconds", 0),
            "average_time_per_question_seconds": ranked_row.get("average_time_per_question_seconds", 0),
            "obtained_marks": ranked_row.get("obtained_marks", 0),
            "total_marks": ranked_row.get("total_marks", 0),
            "attempted_questions": ranked_row.get("attempted_questions", 0),
            "total_questions": ranked_row.get("total_questions", 0),
            "attempts": ranked_row.get("attempts", 0),
            "best_exam": ranked_row.get("best_exam"),
        },
        "profile": {
            "registration_number": profile.get("registration_number", "Unavailable"),
            "applied_position": profile.get("applied_position", "Not provided"),
            "mobile": profile.get("mobile", "N/A"),
            "gender": profile.get("gender", "N/A"),
            "batch": profile.get("batch", "Not provided"),
            "course": profile.get("course", "Not provided"),
            "languages": profile.get("languages", []),
            "computer_proficiency": profile.get("computer_proficiency", ""),
        },
        "attempt_summaries": selected_entry.get("attempt_summaries", []),
        "domains": primary.get("domains", []),
        "skill_radar": primary.get("skill_radar", {}),
        "strengths": primary.get("strengths", []),
        "weaknesses": primary.get("weaknesses", []),
        "recommendations": primary.get("recommendations", []),
        "recommended_courses": primary.get("recommended_courses", []),
        "questions": questions,
        "notes": [],
    }


def _build_multi_top_performer_analysis(
    top_performer: dict[str, Any],
    selected_entry: dict[str, Any],
) -> dict[str, Any]:
    name = top_performer.get("candidate_name", "Unknown Candidate")
    return {
        "candidate_id": top_performer.get("candidate_id", 0),
        "candidate_name": name,
        "rank": top_performer.get("rank", 1),
        "accuracy": top_performer.get("accuracy", 0),
        "marks_percent": top_performer.get("marks_percent", 0),
        "composite_score": top_performer.get("composite_score", 0),
        "speed_score": top_performer.get("speed_score", 0),
        "headline": (
            f"{name} leads the available candidate set with a composite score of "
            f"{top_performer.get('composite_score', 0)}."
        ),
        "insights": [
            f"Average accuracy across attempts is {top_performer.get('accuracy', 0)}%.",
            f"Best exam result is {top_performer.get('best_exam') or 'not available'} at {top_performer.get('best_marks_percent', 0)}%.",
            f"{top_performer.get('attempts', 0)} attempt(s) are included for this candidate.",
        ],
        "recommended_courses": selected_entry.get("primary_attempt", {}).get("recommended_courses", [])[:3],
    }


def _build_multi_aggregate_analysis(
    *,
    ranked_candidates: list[dict[str, Any]],
    attempt_count: int,
) -> dict[str, Any]:
    accuracies = [float(item.get("accuracy") or 0) for item in ranked_candidates]
    marks = [float(item.get("marks_percent") or 0) for item in ranked_candidates]
    composites = [float(item.get("composite_score") or 0) for item in ranked_candidates]
    average_accuracy = round(mean(accuracies), 2) if accuracies else 0.0
    average_marks = round(mean(marks), 2) if marks else 0.0
    average_composite = round(mean(composites), 2) if composites else 0.0
    strong_count = sum(1 for value in accuracies if value >= 80)
    at_risk_count = sum(1 for value in accuracies if value < 50)
    return {
        "headline": "Cohort overview for all available attempts",
        "metrics": {
            "total_candidates": len(ranked_candidates),
            "total_attempts": attempt_count,
            "average_accuracy": average_accuracy,
            "average_marks_percent": average_marks,
            "average_composite_score": average_composite,
            "average_speed_score": 0,
            "strong_performers": strong_count,
            "at_risk_candidates": at_risk_count,
        },
        "insights": [
            f"The live corpus currently includes {len(ranked_candidates)} candidate(s) and {attempt_count} attempt(s).",
            f"Average candidate accuracy is {average_accuracy}% with average marks conversion of {average_marks}%.",
            f"{strong_count} candidate(s) are above 80% average accuracy and {at_risk_count} candidate(s) are below 50%.",
        ],
    }


def _build_candidate_summary(row: dict[str, Any], current_candidate_id: int) -> dict[str, Any]:
    candidate_id = int(row.get("candidate_id") or 0)
    return {
        "candidate_id": candidate_id,
        "candidate_name": str(row.get("candidate_name") or f"Candidate {candidate_id}").strip(),
        "rank": int(row.get("rank") or 0),
        "accuracy": round(float(row.get("accuracy") or 0), 2),
        "marks_percent": round(float(row.get("marks_percent") or 0), 2),
        "composite_score": round(float(row.get("composite_score") or 0), 2),
        "speed_score": round(float(row.get("speed_score") or 0), 2),
        "average_time_per_question_seconds": round(
            float(row.get("average_time_per_question_seconds") or 0), 2
        ),
        "has_full_analysis": candidate_id == current_candidate_id,
        "is_current_candidate": candidate_id == current_candidate_id,
    }


def _build_selected_candidate_detail(
    *,
    selected_row: dict[str, Any],
    analysis_payload: dict[str, Any],
    corpus_payload: dict[str, Any],
    current_candidate_id: int,
) -> dict[str, Any]:
    candidate_id = int(selected_row.get("candidate_id") or 0)
    current_full = candidate_id == current_candidate_id
    base_detail = {
        "candidate_id": candidate_id,
        "candidate_name": str(selected_row.get("candidate_name") or f"Candidate {candidate_id}").strip(),
        "rank": int(selected_row.get("rank") or 0),
        "analysis_scope": "full" if current_full else "summary",
        "summary": {
            "accuracy": round(float(selected_row.get("accuracy") or 0), 2),
            "marks_percent": round(float(selected_row.get("marks_percent") or 0), 2),
            "composite_score": round(float(selected_row.get("composite_score") or 0), 2),
            "speed_score": round(float(selected_row.get("speed_score") or 0), 2),
            "time_taken_seconds": int(selected_row.get("time_taken_seconds") or 0),
            "average_time_per_question_seconds": round(
                float(selected_row.get("average_time_per_question_seconds") or 0),
                2,
            ),
            "obtained_marks": round(float(selected_row.get("obtained_marks") or 0), 2),
            "total_marks": round(float(selected_row.get("total_marks") or 0), 2),
            "attempted_questions": int(selected_row.get("attempted_questions") or 0),
            "total_questions": int(selected_row.get("total_questions") or 0),
        },
        "profile": {},
        "domains": [],
        "skill_radar": {"labels": [], "scores": [], "details": []},
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "recommended_courses": [],
        "questions": [],
        "notes": [],
    }

    if current_full:
        student = analysis_payload.get("student", {})
        base_detail["profile"] = {
            "registration_number": student.get("registration_number", "Unavailable"),
            "applied_position": student.get("applied_position", "Not provided"),
            "mobile": student.get("mobile", "N/A"),
            "gender": student.get("gender", "N/A"),
            "batch": student.get("batch", "Not provided"),
            "course": student.get("course", "Not provided"),
            "languages": student.get("languages", []),
            "computer_proficiency": student.get("computer_proficiency", ""),
            "profile_sections": _profile_section_counts(corpus_payload),
        }
        base_detail["domains"] = analysis_payload.get("domains", [])
        base_detail["skill_radar"] = analysis_payload.get("skill_radar", {})
        base_detail["strengths"] = analysis_payload.get("strengths", [])
        base_detail["weaknesses"] = analysis_payload.get("weaknesses", [])
        base_detail["recommendations"] = analysis_payload.get("recommendations", [])
        base_detail["recommended_courses"] = analysis_payload.get("recommended_courses", [])
        base_detail["questions"] = analysis_payload.get("questions", [])
        return base_detail

    base_detail["notes"] = [
        "Detailed question-level analysis is not available for this candidate in the current live corpus.",
        "The dashboard shows ranking-level metrics until detailed attempt and profile data are provided for each candidate.",
    ]
    return base_detail


def _build_top_performer_analysis(
    *,
    top_performer: dict[str, Any],
    analysis_payload: dict[str, Any],
    current_candidate_id: int,
) -> dict[str, Any]:
    candidate_id = int(top_performer.get("candidate_id") or 0)
    details = {
        "candidate_id": candidate_id,
        "candidate_name": top_performer.get("candidate_name", "Unknown Candidate"),
        "rank": int(top_performer.get("rank") or 1),
        "accuracy": round(float(top_performer.get("accuracy") or 0), 2),
        "marks_percent": round(float(top_performer.get("marks_percent") or 0), 2),
        "composite_score": round(float(top_performer.get("composite_score") or 0), 2),
        "speed_score": round(float(top_performer.get("speed_score") or 0), 2),
        "headline": "",
        "insights": [],
        "recommended_courses": [],
    }

    details["headline"] = (
        f"{details['candidate_name']} leads the cohort with a composite score of "
        f"{details['composite_score']} and accuracy of {details['accuracy']}%."
    )
    details["insights"] = [
        f"Marks conversion stands at {details['marks_percent']}% across attempted questions.",
        f"Speed efficiency score is {details['speed_score']}, combining pace with scored output.",
    ]

    if candidate_id == current_candidate_id:
        strengths = analysis_payload.get("strengths", [])
        weaknesses = analysis_payload.get("weaknesses", [])
        if strengths:
            details["insights"].append(f"Strongest areas: {', '.join(strengths[:3])}.")
        if weaknesses:
            details["insights"].append(f"Improvement still remains in: {', '.join(weaknesses[:2])}.")
        details["recommended_courses"] = analysis_payload.get("recommended_courses", [])[:3]
    else:
        details["insights"].append(
            "Only summary-level ranking data is available for this candidate in the current corpus."
        )

    return details


def _build_aggregate_analysis(
    *,
    rankings: list[dict[str, Any]],
    analysis_payload: dict[str, Any],
    exam_name: str,
) -> dict[str, Any]:
    accuracies = [float(item.get("accuracy") or 0) for item in rankings]
    marks = [float(item.get("marks_percent") or 0) for item in rankings]
    composite_scores = [float(item.get("composite_score") or 0) for item in rankings]
    speed_scores = [float(item.get("speed_score") or 0) for item in rankings]
    average_accuracy = round(mean(accuracies), 2) if accuracies else 0.0
    average_marks = round(mean(marks), 2) if marks else 0.0
    average_composite = round(mean(composite_scores), 2) if composite_scores else 0.0
    average_speed = round(mean(speed_scores), 2) if speed_scores else 0.0
    strong_count = sum(1 for value in accuracies if value >= 80)
    at_risk_count = sum(1 for value in accuracies if value < 50)

    weakest_domains = analysis_payload.get("weaknesses", [])
    strongest_domains = analysis_payload.get("strengths", [])
    insights = [
        f"{exam_name} currently covers {len(rankings)} ranked candidate(s) in the live dashboard.",
        f"Average cohort accuracy is {average_accuracy}% and average marks conversion is {average_marks}%.",
        f"{strong_count} candidate(s) are performing strongly while {at_risk_count} candidate(s) need closer intervention.",
    ]
    if strongest_domains:
        insights.append(f"Observed strongest competency cluster: {', '.join(strongest_domains[:3])}.")
    if weakest_domains:
        insights.append(f"Observed weakest competency cluster: {', '.join(weakest_domains[:3])}.")

    return {
        "headline": f"Cohort overview for {exam_name}",
        "metrics": {
            "total_candidates": len(rankings),
            "average_accuracy": average_accuracy,
            "average_marks_percent": average_marks,
            "average_composite_score": average_composite,
            "average_speed_score": average_speed,
            "strong_performers": strong_count,
            "at_risk_candidates": at_risk_count,
        },
        "insights": insights,
    }


def _profile_section_counts(corpus_payload: dict[str, Any]) -> list[dict[str, Any]]:
    profile_data = corpus_payload.get("apis", {}).get("candidate_profile", {}).get("data", {})
    sections = profile_data.get("sections", []) if isinstance(profile_data, dict) else []
    items = []
    for index, section in enumerate(sections, start=1):
        if isinstance(section, list):
            items.append({"section": f"Section {index}", "items": len(section)})
        elif isinstance(section, dict):
            items.append({"section": f"Section {index}", "items": 1})
    return items
