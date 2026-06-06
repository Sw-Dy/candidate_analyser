from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import DOMAIN_LABELS, RECOMMENDATION_URL


FALLBACK_SKILLS = [
    "Programming",
    "Problem Solving",
    "Reasoning",
    "Backend",
    "Frontend",
    "Database",
    "Communication",
    "Design",
]

SKILL_KEYWORDS = {
    "Programming": ["code", "program", "python", "java", "function", "algorithm"],
    "Problem Solving": ["solve", "logic", "algorithm", "aptitude", "problem"],
    "Reasoning": ["reason", "analogy", "pattern", "aptitude", "logic"],
    "Backend": ["api", "server", "backend", "flask", "django", "fastapi"],
    "Frontend": ["frontend", "html", "css", "javascript", "react", "ui"],
    "Database": ["database", "sql", "query", "dbms", "table"],
    "Communication": ["communication", "email", "writing", "verbal", "stakeholder"],
    "Design": ["design", "ux", "figma", "wireframe", "layout"],
    "ML": ["model", "dataset", "training", "classification", "regression"],
    "DevOps": ["docker", "deployment", "pipeline", "linux", "cloud"],
}


class SkillIntelligenceService:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(30.0)

    async def enrich(
        self,
        *,
        candidate_profile: dict[str, Any],
        exam: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = self._build_prompt(
            candidate_profile=candidate_profile,
            exam=exam,
            questions=questions,
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(RECOMMENDATION_URL, json={"content": prompt})
                response.raise_for_status()
                try:
                    body = response.json()
                except ValueError:
                    body = {"response": response.text}
            parsed = self._parse_response(body)
            source = "ai"
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            parsed = self._fallback_enrichment(candidate_profile, exam, questions)
            body = None
            source = "fallback"

        return {
            "skills": parsed["skills"],
            "questions": parsed["questions"],
            "source": source,
            "raw_api": {
                "url": RECOMMENDATION_URL,
                "request_body": {"content": prompt},
                "ok": source == "ai",
                "error": None if source == "ai" else "AI enrichment fallback used",
                "body": body,
            },
        }

    def _build_prompt(
        self,
        *,
        candidate_profile: dict[str, Any],
        exam: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> str:
        compact_questions = [
            {
                "question_id": question["question_id"],
                "question_text": question["question_text"],
                "question_type": question["question_type"],
                "domain": question["domain"],
                "topic": question["topic"],
            }
            for question in questions
        ]
        compact_profile = {
            "applied_role": candidate_profile.get("position"),
            "self_reported_proficiency": candidate_profile.get("computer_proficiency"),
            "languages": candidate_profile.get("languages", []),
        }
        instructions = {
            "skills": [
                "Return 5 to 8 concise skill labels relevant to the role and assessment.",
                "Prefer labels like Programming, Database, Problem Solving, Communication, Reasoning, Backend, Frontend, ML, Design.",
            ],
            "questions": [
                "For every question, assign one primary_skill and up to two supporting_skills from the generated skill labels.",
                "Add difficulty_label using only Easy, Intermediate, Hard.",
                "Add difficulty_rating as an integer from 1 to 5.",
            ],
            "format": {
                "skills": ["Programming", "Problem Solving"],
                "questions": [
                    {
                        "question_id": 1,
                        "primary_skill": "Programming",
                        "supporting_skills": ["Problem Solving"],
                        "difficulty_label": "Intermediate",
                        "difficulty_rating": 3,
                    }
                ],
            },
        }
        return (
            "Analyze the candidate role and assessment questions. Return strict JSON only. "
            f"Instructions: {json.dumps(instructions)} "
            f"Candidate Profile: {json.dumps(compact_profile)} "
            f"Exam: {json.dumps(exam)} "
            f"Questions: {json.dumps(compact_questions)}"
        )

    def _parse_response(self, body: dict[str, Any]) -> dict[str, Any]:
        response_text = str(body.get("response", "")).strip()
        parsed = json.loads(response_text)
        skills = [str(item).strip() for item in parsed.get("skills", []) if str(item).strip()]
        question_items = parsed.get("questions", [])
        if not skills or not isinstance(question_items, list):
            raise ValueError("Incomplete enrichment response")
        return {
            "skills": skills[:8],
            "questions": [self._normalize_question_item(item) for item in question_items if isinstance(item, dict)],
        }

    def _fallback_enrichment(
        self,
        candidate_profile: dict[str, Any],
        exam: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        role_text = " ".join(
            str(value or "")
            for value in [
                candidate_profile.get("position"),
                candidate_profile.get("computer_proficiency"),
                exam.get("name"),
            ]
        ).lower()

        selected_skills = []
        for skill in FALLBACK_SKILLS + DOMAIN_LABELS:
            keywords = SKILL_KEYWORDS.get(skill, [skill.lower()])
            if any(keyword in role_text for keyword in keywords):
                selected_skills.append(skill)
        if not selected_skills:
            selected_skills = FALLBACK_SKILLS[:6]

        selected_skills = list(dict.fromkeys(selected_skills))[:8]
        question_items = [self._fallback_question_item(question, selected_skills) for question in questions]
        return {"skills": selected_skills, "questions": question_items}

    def _fallback_question_item(
        self,
        question: dict[str, Any],
        selected_skills: list[str],
    ) -> dict[str, Any]:
        corpus = " ".join(
            str(question.get(field, "")) for field in ["question_text", "domain", "topic", "question_type"]
        ).lower()
        primary_skill = question.get("domain") if question.get("domain") in selected_skills else None
        supporting_skills: list[str] = []

        if primary_skill is None:
            for skill in selected_skills:
                if any(keyword in corpus for keyword in SKILL_KEYWORDS.get(skill, [])):
                    primary_skill = skill
                    break
        if primary_skill is None:
            primary_skill = selected_skills[0]

        for skill in selected_skills:
            if skill == primary_skill:
                continue
            if any(keyword in corpus for keyword in SKILL_KEYWORDS.get(skill, [])):
                supporting_skills.append(skill)
            if len(supporting_skills) == 2:
                break

        difficulty_rating = self._fallback_difficulty_rating(question)
        return {
            "question_id": question["question_id"],
            "primary_skill": primary_skill,
            "supporting_skills": supporting_skills,
            "difficulty_label": self._difficulty_label(difficulty_rating),
            "difficulty_rating": difficulty_rating,
        }

    def _normalize_question_item(self, item: dict[str, Any]) -> dict[str, Any]:
        rating = int(item.get("difficulty_rating") or 3)
        rating = max(1, min(5, rating))
        primary_skill = str(item.get("primary_skill") or "").strip() or "Problem Solving"
        supporting_skills = [
            str(skill).strip()
            for skill in item.get("supporting_skills", [])
            if str(skill).strip() and str(skill).strip() != primary_skill
        ][:2]
        label = str(item.get("difficulty_label") or self._difficulty_label(rating)).strip().title()
        if label not in {"Easy", "Intermediate", "Hard"}:
            label = self._difficulty_label(rating)
        return {
            "question_id": int(item.get("question_id") or 0),
            "primary_skill": primary_skill,
            "supporting_skills": supporting_skills,
            "difficulty_label": label,
            "difficulty_rating": rating,
        }

    def _fallback_difficulty_rating(self, question: dict[str, Any]) -> int:
        text = str(question.get("question_text", ""))
        options = re.findall(r"\b[A-Z]{2,}\b", text)
        if len(text) > 180 or "coding" in text.lower() or "sql" in text.lower():
            return 4
        if len(text) > 90 or len(options) > 4:
            return 3
        return 2

    def _difficulty_label(self, rating: int) -> str:
        if rating >= 4:
            return "Hard"
        if rating <= 2:
            return "Easy"
        return "Intermediate"
