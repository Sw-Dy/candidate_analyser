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
        shortlisted_courses = self._shortlist_courses(payload, courses)
        prompt = self._build_prompt(payload, shortlisted_courses)
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
            fallback_courses = self._fallback_course_recommendations(shortlisted_courses)
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
        recommended_courses = parsed.get("recommended_courses") or self._fallback_course_recommendations(
            shortlisted_courses
        )

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

    def _build_prompt(self, payload: dict[str, Any], shortlisted_courses: list[dict[str, Any]]) -> str:
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
            "recommended_courses must contain 3 to 5 objects with keys: course_id, course_name, priority, reason. "
            "Only recommend from the provided course shortlist. "
            f"Analytics: {json.dumps(compact_payload)} "
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
                }
            )
        return {
            "recommendations": [str(item) for item in recommendations if str(item).strip()][:4],
            "recommended_courses": [item for item in recommended_courses if item["course_name"]][:5],
        }

    def _fallback_recommendations(self, payload: dict[str, Any]) -> list[str]:
        weakest = payload["weaknesses"][0] if payload["weaknesses"] else "core concepts"
        strongest = payload["strengths"][0] if payload["strengths"] else "foundational topics"
        average_time = payload["summary"]["average_time_per_question_seconds"]
        weakest_skill = "skill gaps"
        skill_details = payload.get("skill_radar", {}).get("details", [])
        if skill_details:
            weakest_skill = sorted(skill_details, key=lambda item: item.get("score", 0))[0].get("skill", weakest_skill)
        return [
            f"Prioritize revision in {weakest} through 20-minute focused practice blocks.",
            f"Use {strongest} as a confidence anchor before moving into weaker sections.",
            f"Target an average response time below {round(average_time, 1)} seconds per question.",
            f"Strengthen {weakest_skill} with guided practice and concept recap after each mock test.",
        ]

    def _shortlist_courses(self, payload: dict[str, Any], courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not courses:
            return []

        keywords = set()
        for value in payload.get("strengths", []) + payload.get("weaknesses", []):
            keywords.update(self._tokenize(value))
        for domain in payload.get("domains", []):
            for topic in domain.get("weak_topics", []):
                keywords.update(self._tokenize(topic))
            if domain.get("classification") == "Weak":
                keywords.update(self._tokenize(domain.get("domain", "")))
        for detail in payload.get("skill_radar", {}).get("details", []):
            if detail.get("score", 0) < 60:
                keywords.update(self._tokenize(detail.get("skill", "")))
        keywords.update(self._tokenize(payload.get("student", {}).get("applied_position", "")))

        scored_courses = []
        for course in courses:
            corpus = " ".join(
                str(course.get(key, ""))
                for key in ["CourseName", "CategoryName", "CourseShortDesc", "CourseOriginalLongDesc"]
            ).lower()
            score = sum(2 if keyword in str(course.get("CourseName", "")).lower() else 1 for keyword in keywords if keyword in corpus)
            if course.get("PublishYN"):
                score += 2
            if course.get("ActiveYN"):
                score += 1
            if course.get("SkillLevelName"):
                score += 1
            scored_courses.append((score, course))

        scored_courses.sort(key=lambda item: item[0], reverse=True)
        shortlisted = []
        for score, course in scored_courses[:12]:
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
                }
            )
        return shortlisted

    def _fallback_course_recommendations(self, shortlisted_courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        recommendations = []
        for course in shortlisted_courses[:4]:
            recommendations.append(
                {
                    "course_id": course["course_id"],
                    "course_name": course["course_name"],
                    "priority": "High" if course.get("match_score", 0) >= 4 else "Medium",
                    "reason": course.get("short_description") or f"Useful for strengthening {course.get('category', 'core')} skills.",
                }
            )
        return recommendations

    def _tokenize(self, value: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", str(value).lower()) if len(token) > 2}
