from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import RECOMMENDATION_URL


class RecommendationService:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(30.0)

    async def generate(self, payload: dict[str, Any], courses: list[dict[str, Any]]) -> dict[str, Any]:
        weakness_targets = self._weakness_targets(payload)
        shortlisted_courses = self._shortlist_courses(weakness_targets, courses)
        prompt = self._build_prompt(payload, shortlisted_courses, weakness_targets)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    RECOMMENDATION_URL,
                    json={"content": prompt},
                )
                response.raise_for_status()
                try:
                    body = response.json()
                except ValueError:
                    body = {"response": response.text}
        except (httpx.HTTPError, ValueError) as exc:
            fallback_courses = self._fallback_course_recommendations(shortlisted_courses, weakness_targets)
            return {
                "recommendations": self._fallback_recommendations(payload),
                "recommended_courses": fallback_courses,
                "raw_api": {
                    "url": RECOMMENDATION_URL,
                    "request_body": {"content": prompt},
                    "ok": False,
                    "error": str(exc),
                    "body": None,
                },
            }

        recommendation_text = str(body.get("response", "")).strip()
        parsed = self._parse_response(recommendation_text) if recommendation_text else {}
        recommendations = parsed.get("recommendations") or self._fallback_recommendations(payload)
        recommended_courses = self._validate_recommended_courses(
            parsed.get("recommended_courses") or self._fallback_course_recommendations(shortlisted_courses, weakness_targets),
            weakness_targets,
            shortlisted_courses,
        )
        if not recommended_courses:
            recommended_courses = self._fallback_course_recommendations(shortlisted_courses, weakness_targets)

        return {
            "recommendations": recommendations,
            "recommended_courses": recommended_courses,
            "raw_api": {
                "url": RECOMMENDATION_URL,
                "request_body": {"content": prompt},
                "ok": True,
                "error": None,
                "body": body,
            },
        }

    def _build_prompt(
        self,
        payload: dict[str, Any],
        shortlisted_courses: list[dict[str, Any]],
        weakness_targets: list[dict[str, str]],
    ) -> str:
        compact_payload = {
            "student": payload["student"],
            "exam": payload["exam"],
            "summary": payload["summary"],
            "domains": payload["domains"],
            "strengths": payload["strengths"],
            "weaknesses": payload["weaknesses"],
            "skill_radar": payload.get("skill_radar", {}),
            "top_performer": payload.get("top_performer", {}),
        }
        return (
            "Analyze the following student assessment analytics and course catalog shortlist. "
            "Return strict JSON with exactly two top-level keys: recommendations and recommended_courses. "
            "recommendations must contain 4 concise action strings. "
            "recommended_courses must contain 0 to 5 objects with keys: course_id, course_name, priority, reason, linked_domain, linked_topic, improvement_objective. "
            "Only recommend from the provided course shortlist. "
            "Every course must directly address one Weakness Target. Do not recommend unrelated courses. "
            f"Analytics: {json.dumps(compact_payload)} "
            f"Weakness Targets: {json.dumps(weakness_targets)} "
            f"Course Shortlist: {json.dumps(shortlisted_courses)}"
        )

    def _parse_response(self, response_text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            lines = []
            for raw_line in response_text.splitlines():
                cleaned = raw_line.strip(" -0123456789.")
                if cleaned:
                    lines.append(cleaned)
            return {"recommendations": lines[:4], "recommended_courses": []}

        recommendations = parsed.get("recommendations", [])
        recommended_courses = []
        for item in parsed.get("recommended_courses", []):
            if not isinstance(item, dict):
                continue
            recommended_courses.append(
                {
                    "course_id": int(item.get("course_id") or 0),
                    "course_name": str(item.get("course_name") or "").strip(),
                    "priority": str(item.get("priority") or "Medium").title(),
                    "reason": str(item.get("reason") or "").strip(),
                    "linked_domain": str(item.get("linked_domain") or "").strip(),
                    "linked_topic": str(item.get("linked_topic") or "").strip(),
                    "improvement_objective": str(item.get("improvement_objective") or "").strip(),
                }
            )
        return {
            "recommendations": [str(item) for item in recommendations if str(item).strip()][:4],
            "recommended_courses": [item for item in recommended_courses if item["course_name"]][:5],
        }

    def _fallback_recommendations(self, payload: dict[str, Any]) -> list[str]:
        targets = self._weakness_targets(payload)
        weakest = targets[0]["weak_topic"] if targets else (payload["weaknesses"][0] if payload["weaknesses"] else "core concepts")
        strongest = payload["strengths"][0] if payload["strengths"] else "foundational topics"
        average_time = payload["summary"]["average_time_per_question_seconds"]
        weakest_skill = "skill gaps"
        skill_details = payload.get("skill_radar", {}).get("details", [])
        if skill_details:
            weakest_detail = sorted(skill_details, key=lambda item: item.get("score", 0))[0]
            weakest_skill = weakest_detail.get("domain") or weakest_detail.get("skill") or weakest_skill
        return [
            f"Prioritize revision in {weakest} through 20-minute focused practice blocks.",
            f"Use {strongest} as a confidence anchor before moving into weaker sections.",
            f"Target an average response time below {round(average_time, 1)} seconds per question.",
            f"Strengthen {weakest_skill} with guided practice and concept recap after each mock test.",
        ]

    def _weakness_targets(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        targets = []
        for domain in payload.get("domains", []):
            domain_name = str(domain.get("domain") or "").strip()
            weak_topics = [str(topic or "").strip() for topic in domain.get("weak_topics", []) if str(topic or "").strip()]
            if float(domain.get("score_percent") or 0) < 70:
                if not weak_topics:
                    weak_topics = [domain_name]
                for topic in weak_topics:
                    targets.append(
                        {
                            "weak_domain": domain_name,
                            "weak_topic": topic,
                            "improvement_objective": f"Improve {topic} within {domain_name}".strip(),
                        }
                    )

        for question in payload.get("questions", []):
            if question.get("status") not in {"Incorrect", "Partial"}:
                continue
            domain_name = str(question.get("domain") or "").strip()
            topic = str(question.get("topic") or question.get("primary_skill") or "").strip()
            if not topic:
                continue
            targets.append(
                {
                    "weak_domain": domain_name,
                    "weak_topic": topic,
                    "improvement_objective": f"Strengthen {topic}".strip(),
                }
            )

        unique = {}
        for target in targets:
            key = (target["weak_domain"].lower(), target["weak_topic"].lower())
            unique[key] = target
        return list(unique.values())

    def _shortlist_courses(self, weakness_targets: list[dict[str, str]], courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not courses or not weakness_targets:
            return []

        scored_courses = []
        for course in courses:
            corpus = " ".join(
                str(course.get(key, ""))
                for key in ["CourseName", "CategoryName", "CourseShortDesc", "CourseOriginalLongDesc"]
            ).lower()
            best_target = None
            best_score = 0
            for target in weakness_targets:
                keywords = self._tokenize(target.get("weak_topic", "")) | self._tokenize(target.get("weak_domain", ""))
                score = sum(
                    2 if keyword in str(course.get("CourseName", "")).lower() else 1
                    for keyword in keywords
                    if keyword in corpus
                )
                if score > best_score:
                    best_score = score
                    best_target = target
            if best_score <= 0 or best_target is None:
                continue
            score = best_score
            if course.get("PublishYN"):
                score += 2
            if course.get("ActiveYN"):
                score += 1
            if course.get("SkillLevelName"):
                score += 1
            scored_courses.append((score, course, best_target))

        scored_courses.sort(key=lambda item: item[0], reverse=True)
        shortlisted = []
        for score, course, target in scored_courses[:12]:
            shortlisted.append(
                {
                    "course_id": int(course.get("IDCourse") or 0),
                    "course_name": str(course.get("CourseName") or "").strip(),
                    "category": str(course.get("CategoryName") or "").strip(),
                    "skill_level": str(course.get("SkillLevelName") or "General").strip() or "General",
                    "duration": f"{course.get('CourseDuration', 0)} {course.get('DurationType', '').strip()}".strip(),
                    "publish": bool(course.get("PublishYN")),
                    "short_description": str(course.get("CourseShortDesc") or "").strip(),
                    "match_score": score,
                    "linked_domain": target["weak_domain"],
                    "linked_topic": target["weak_topic"],
                    "improvement_objective": target["improvement_objective"],
                }
            )
        return shortlisted

    def _validate_recommended_courses(
        self,
        recommendations: list[dict[str, Any]],
        weakness_targets: list[dict[str, str]],
        shortlisted_courses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        target_topics = {target["weak_topic"].lower() for target in weakness_targets}
        shortlist_by_id = {int(course.get("course_id") or 0): course for course in shortlisted_courses}
        shortlist_by_name = {str(course.get("course_name") or "").lower(): course for course in shortlisted_courses}
        valid = []
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            course_id = int(item.get("course_id") or 0)
            course_name = str(item.get("course_name") or "").strip()
            matched_course = shortlist_by_id.get(course_id) or shortlist_by_name.get(course_name.lower())
            if matched_course is None:
                continue
            linked_topic = str(item.get("linked_topic") or matched_course.get("linked_topic") or "").strip()
            if linked_topic.lower() not in target_topics:
                continue
            valid.append(
                {
                    "course_id": int(matched_course.get("course_id") or course_id),
                    "course_name": matched_course.get("course_name") or course_name,
                    "priority": str(item.get("priority") or "Medium").title(),
                    "reason": str(item.get("reason") or matched_course.get("short_description") or "").strip(),
                    "linked_domain": str(item.get("linked_domain") or matched_course.get("linked_domain") or "").strip(),
                    "linked_topic": linked_topic,
                    "improvement_objective": str(
                        item.get("improvement_objective") or matched_course.get("improvement_objective") or ""
                    ).strip(),
                }
            )
        return valid[:5]

    def _fallback_course_recommendations(
        self,
        shortlisted_courses: list[dict[str, Any]],
        weakness_targets: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if not weakness_targets:
            return []
        recommendations = []
        for course in shortlisted_courses[:4]:
            recommendations.append(
                {
                    "course_id": course["course_id"],
                    "course_name": course["course_name"],
                    "priority": "High" if course.get("match_score", 0) >= 4 else "Medium",
                    "reason": course.get("short_description")
                    or f"Useful for strengthening {course.get('linked_topic')}.",
                    "linked_domain": course.get("linked_domain", ""),
                    "linked_topic": course.get("linked_topic", ""),
                    "improvement_objective": course.get("improvement_objective", ""),
                }
            )
        return recommendations

    def _tokenize(self, value: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", str(value).lower()) if len(token) > 2}
