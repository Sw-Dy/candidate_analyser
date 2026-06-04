from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import RECOMMENDATION_URL


class RecommendationService:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(30.0)

    async def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = self._build_prompt(payload)
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
            return {
                "recommendations": self._fallback_recommendations(payload),
                "raw_api": {
                    "url": RECOMMENDATION_URL,
                    "request_body": {"content": prompt},
                    "ok": False,
                    "error": str(exc),
                    "body": None,
                },
            }

        recommendation_text = str(body.get("response", "")).strip()
        recommendations = (
            self._parse_response(recommendation_text)
            if recommendation_text
            else self._fallback_recommendations(payload)
        )
        if not recommendations:
            recommendations = self._fallback_recommendations(payload)

        return {
            "recommendations": recommendations,
            "raw_api": {
                "url": RECOMMENDATION_URL,
                "request_body": {"content": prompt},
                "ok": True,
                "error": None,
                "body": body,
            },
        }

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        compact_payload = {
            "student": payload["student"],
            "exam": payload["exam"],
            "summary": payload["summary"],
            "domains": payload["domains"],
            "strengths": payload["strengths"],
            "weaknesses": payload["weaknesses"],
        }
        return (
            "Analyze the following student assessment analytics and return JSON with "
            "a top-level key named recommendations containing 4 concise action items. "
            "Each action item should be a plain string. "
            f"Analytics: {json.dumps(compact_payload)}"
        )

    def _parse_response(self, response_text: str) -> list[str]:
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            lines = []
            for raw_line in response_text.splitlines():
                cleaned = raw_line.strip(" -0123456789.")
                if cleaned:
                    lines.append(cleaned)
            return lines[:4]

        recommendations = parsed.get("recommendations", [])
        return [str(item) for item in recommendations if str(item).strip()][:4]

    def _fallback_recommendations(self, payload: dict[str, Any]) -> list[str]:
        weakest = payload["weaknesses"][0] if payload["weaknesses"] else "core concepts"
        strongest = payload["strengths"][0] if payload["strengths"] else "foundational topics"
        average_time = payload["summary"]["average_time_per_question_seconds"]
        return [
            f"Prioritize revision in {weakest} through 20-minute focused practice blocks.",
            f"Use {strongest} as a confidence anchor before moving into weaker sections.",
            f"Target an average response time below {round(average_time, 1)} seconds per question.",
            "Review every incorrect answer and write down the concept that led to the mistake.",
        ]
