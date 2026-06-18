from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import RECOMMENDATION_URL


PLACEHOLDER_LABELS = {"", "Pending AI Label", "pending ai label", "None", "none", "null"}
VAGUE_DOMAIN_LABELS = {
    "general",
    "concepts",
    "technical",
    "technical knowledge",
    "programming",
    "software",
    "database",
    "networking",
    "web",
    "backend",
    "frontend",
    "computer science",
    "information technology",
}
VAGUE_TOPIC_LABELS = {
    "general",
    "concepts",
    "technical",
    "technical knowledge",
    "programming",
    "software",
    "database",
    "networking",
    "web",
    "backend",
    "frontend",
}


class AIEnrichmentError(RuntimeError):
    pass


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
        retry_body = None

        try:
            body = await self._post_prompt(prompt)
            parsed = self._parse_response(body)
            for _ in range(2):
                retry_body = await self._retry_incomplete_ai_labels(
                    parsed=parsed,
                    candidate_profile=candidate_profile,
                    exam=exam,
                    questions=questions,
                )
                if retry_body is None:
                    break
                parsed = self._merge_retry_response(parsed, retry_body, questions)

            parsed = self._complete_question_items(parsed, questions)
            self._raise_for_missing_ai_labels(parsed)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError, AIEnrichmentError) as exc:
            raise AIEnrichmentError(
                f"ChatGPT labeling failed for {len(questions)} question(s): {exc}"
            ) from exc

        return {
            "skills": parsed["skills"],
            "questions": parsed["questions"],
            "source": "ai",
            "raw_api": {
                "url": RECOMMENDATION_URL,
                "request_body": {"content": prompt},
                "ok": True,
                "error": None,
                "body": body,
                "retry_body": retry_body,
            },
        }

    async def summarize_strengths_weaknesses(
        self,
        *,
        candidate_profile: dict[str, Any],
        exam: dict[str, Any],
        summary: dict[str, Any],
        domains: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = self._build_strength_weakness_prompt(
            candidate_profile=candidate_profile,
            exam=exam,
            summary=summary,
            domains=domains,
            questions=questions,
        )
        try:
            body = await self._post_prompt(prompt)
            parsed = self._parse_strength_weakness_response(body)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            parsed = self._fallback_strength_weakness_labels(domains=domains, questions=questions)
            return {
                "strengths": parsed["strengths"],
                "weaknesses": parsed["weaknesses"],
                "raw_api": {
                    "url": RECOMMENDATION_URL,
                    "request_body": {"content": prompt},
                    "ok": False,
                    "error": str(exc),
                    "body": locals().get("body"),
                    "fallback_source": "domain_score_evidence",
                },
            }

        return {
            "strengths": parsed["strengths"],
            "weaknesses": parsed["weaknesses"],
            "raw_api": {
                "url": RECOMMENDATION_URL,
                "request_body": {"content": prompt},
                "ok": True,
                "error": None,
                "body": body,
            },
        }

    async def _post_prompt(self, prompt: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(RECOMMENDATION_URL, json={"content": prompt})
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return {"response": response.text}

    def _build_prompt(
        self,
        *,
        candidate_profile: dict[str, Any],
        exam: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> str:
        compact_questions = [self._question_prompt_payload(question) for question in questions]
        compact_profile = {
            "applied_role": candidate_profile.get("position"),
            "self_reported_proficiency": candidate_profile.get("computer_proficiency"),
            "languages": candidate_profile.get("languages", []),
        }
        instructions = {
            "hard_requirements": [
                "Return strict JSON only.",
                "Return exactly one questions item for every input question_id.",
                "Do not return null, empty strings, Pending AI Label, General, Concepts, Other, or Miscellaneous for domain/topic/primary_skill.",
                "Do not return vague one-word domains such as Database, Networking, Programming, Web, Backend, Frontend, Software, or Technical.",
                "Domain must be a specific assessment area or subfield, usually 2 to 5 words.",
                "Topic must be the exact concept being tested; one-word topics are allowed only for precise acronyms or named technologies.",
                "Use question_text, correct_answer, selected_answer, and question_type when deriving labels.",
                "The labels must be generated by you from the supplied question content, not copied from placeholder data.",
            ],
            "json_shape": {
                "skills": ["specific skill label"],
                "questions": [
                    {
                        "question_id": "same numeric id from input",
                        "domain": "specific non-vague domain label",
                        "topic": "specific concept tested",
                        "primary_skill": "specific skill label",
                        "supporting_skills": ["optional specific skill label"],
                        "difficulty_label": "Easy | Intermediate | Hard",
                        "difficulty_rating": "integer 1 to 5",
                    }
                ],
            },
        }
        return (
            "You are the authoritative labeling service for candidate assessment analytics. "
            "Generate fresh, specific domain/topic/skill labels from the provided question content. "
            f"Instructions: {json.dumps(instructions)} "
            f"Candidate Profile: {json.dumps(compact_profile)} "
            f"Exam: {json.dumps(exam)} "
            f"Questions: {json.dumps(compact_questions)}"
        )

    def _build_strength_weakness_prompt(
        self,
        *,
        candidate_profile: dict[str, Any],
        exam: dict[str, Any],
        summary: dict[str, Any],
        domains: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> str:
        compact_questions = [
            {
                "question_id": question.get("question_id"),
                "domain": question.get("domain"),
                "topic": question.get("topic"),
                "primary_skill": question.get("primary_skill"),
                "marks_obtained": question.get("marks_obtained"),
                "full_marks": question.get("full_marks"),
                "status": question.get("status"),
            }
            for question in questions
        ]
        instructions = {
            "hard_requirements": [
                "Return strict JSON only.",
                "Use only the supplied domain/topic/skill evidence.",
                "Do not use fixed generic labels or a template.",
                "Group related question skills into 2 to 5 concise strength labels and 2 to 5 concise weakness labels.",
                "Each label must be a readable capability area, not a sentence and not a marks formula.",
                "Prefer domain-level capability labels so dashboards do not show too many variables.",
            ],
            "json_shape": {
                "strengths": ["capability label"],
                "weaknesses": ["capability label"],
            },
        }
        payload = {
            "candidate_profile": {
                "applied_role": candidate_profile.get("position"),
                "self_reported_proficiency": candidate_profile.get("computer_proficiency"),
                "languages": candidate_profile.get("languages", []),
            },
            "exam": exam,
            "summary": summary,
            "domains": domains,
            "questions": compact_questions,
        }
        return (
            "Label candidate strengths and weaknesses for an assessment dashboard. "
            f"Instructions: {json.dumps(instructions)} "
            f"Evidence: {json.dumps(payload)}"
        )

    async def _retry_incomplete_ai_labels(
        self,
        *,
        parsed: dict[str, Any],
        candidate_profile: dict[str, Any],
        exam: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        questions_to_fix = self._questions_needing_ai_retry(parsed, questions)
        if not questions_to_fix:
            return None

        retry_prompt = (
            "Your previous response had missing or vague labels. Return strict JSON only as an object "
            "with skills and questions arrays. Fix every listed question. "
            "Domain must be specific and non-vague, usually 2 to 5 words. "
            "Topic must be the exact concept being tested. "
            "Do not use null, General, Concepts, Database, Networking, Programming, Web, Backend, Frontend, Software, or Technical as labels. "
            "Every question must include question_id, domain, topic, primary_skill, supporting_skills, "
            "difficulty_label, and difficulty_rating. "
            f"Candidate Profile: {json.dumps(candidate_profile)} "
            f"Exam: {json.dumps(exam)} "
            f"Questions to fix, with validation_errors: {json.dumps(questions_to_fix)}"
        )
        return await self._post_prompt(retry_prompt)

    def _questions_needing_ai_retry(
        self,
        parsed: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        items_by_id = self._items_by_question_id(parsed, questions)
        questions_to_fix = []
        for question in questions:
            question_id = int(question.get("question_id") or 0)
            item = items_by_id.get(question_id)
            errors = ["missing_question_label"] if item is None else self._label_errors(item)
            if errors:
                payload = self._question_prompt_payload(question)
                payload["validation_errors"] = errors
                questions_to_fix.append(payload)
        return questions_to_fix

    def _merge_retry_response(
        self,
        parsed: dict[str, Any],
        retry_body: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            retry_parsed = self._parse_response(retry_body, require_skills=False)
        except (ValueError, json.JSONDecodeError):
            return parsed
        merged_by_id = self._items_by_question_id(parsed, questions)
        retry_by_id = self._items_by_question_id(retry_parsed, questions)
        retry_items = list(retry_parsed.get("questions", []))
        retry_index = 0

        for question in questions:
            question_id = int(question.get("question_id") or 0)
            current_item = merged_by_id.get(question_id)
            if current_item is not None and not self._label_errors(current_item):
                continue
            retry_item = retry_by_id.get(question_id)
            if retry_item is None and retry_index < len(retry_items):
                retry_item = retry_items[retry_index]
                retry_item["question_id"] = question_id
                retry_index += 1
            if retry_item is not None:
                merged_by_id[question_id] = retry_item

        skills = list(dict.fromkeys(parsed.get("skills", []) + retry_parsed.get("skills", [])))
        return {"skills": skills, "questions": list(merged_by_id.values())}

    def _complete_question_items(
        self,
        parsed: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        skills = [str(item).strip() for item in parsed.get("skills", []) if str(item).strip()]
        completed_items = []
        used_question_ids: set[int] = set()

        for index, item in enumerate(parsed.get("questions", [])):
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_question_item(item)
            if not normalized.get("question_id") and index < len(questions):
                normalized["question_id"] = int(questions[index].get("question_id") or 0)
            if not normalized.get("question_id"):
                continue
            errors = self._label_errors(normalized)
            normalized["label_quality"] = "needs_review" if errors else "specific"
            normalized["label_warnings"] = errors
            normalized["mapping_source"] = "ai"
            completed_items.append(normalized)
            used_question_ids.add(normalized["question_id"])

        for question in questions:
            question_id = int(question.get("question_id") or 0)
            if question_id and question_id not in used_question_ids:
                completed_items.append(self._empty_question_item(question, "ai_missing"))

        question_skills = [item["primary_skill"] for item in completed_items if item.get("primary_skill")]
        return {
            "skills": list(dict.fromkeys(skills + question_skills))[:8],
            "questions": completed_items,
        }

    def _parse_response(self, body: dict[str, Any], *, require_skills: bool = True) -> dict[str, Any]:
        if isinstance(body.get("questions"), list):
            parsed = body
        else:
            response_text = self._first_response_text(body)
            parsed = json.loads(self._extract_json(response_text))

        question_items = parsed.get("questions", [])
        if not isinstance(question_items, list) or not question_items:
            raise ValueError("Incomplete enrichment response: missing questions array")

        normalized_questions = [
            self._normalize_question_item(item)
            for item in question_items
            if isinstance(item, dict)
        ]
        skills = [str(item).strip() for item in parsed.get("skills", []) if str(item).strip()]
        if not skills:
            skills = [item["primary_skill"] for item in normalized_questions if item.get("primary_skill")]
        if require_skills and not skills:
            raise ValueError("Incomplete enrichment response: missing skills")

        return {"skills": list(dict.fromkeys(skills))[:8], "questions": normalized_questions}

    def _parse_strength_weakness_response(self, body: dict[str, Any]) -> dict[str, Any]:
        if isinstance(body.get("strengths"), list) or isinstance(body.get("weaknesses"), list):
            parsed = body
        else:
            response_text = self._first_response_text(body)
            parsed = json.loads(self._extract_json(response_text))

        strengths = self._clean_label_list(parsed.get("strengths", []))[:5]
        weaknesses = self._clean_label_list(parsed.get("weaknesses", []))[:5]
        if not strengths and not weaknesses:
            raise ValueError("Incomplete strength/weakness response")
        return {"strengths": strengths, "weaknesses": weaknesses}

    def _first_response_text(self, body: dict[str, Any]) -> str:
        for key in ["response", "content", "message", "answer", "data", "result"]:
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = self._first_response_text(value)
                if nested:
                    return nested
        choices = body.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                nested = self._first_response_text(choice)
                if nested:
                    return nested
        return ""

    def _fallback_strength_weakness_labels(
        self,
        *,
        domains: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        scored_domains = []
        for domain in domains:
            label = self._clean_label(domain.get("domain"))
            if not label:
                continue
            scored_domains.append(
                {
                    "label": label,
                    "score": float(domain.get("score_percent") or domain.get("accuracy") or 0),
                    "questions": int(domain.get("total_questions") or 0),
                }
            )

        strengths = [
            item["label"]
            for item in sorted(
                scored_domains,
                key=lambda value: (value["score"], value["questions"], value["label"]),
                reverse=True,
            )
            if item["score"] >= 70
        ][:5]
        weaknesses = [
            item["label"]
            for item in sorted(scored_domains, key=lambda value: (value["score"], -value["questions"], value["label"]))
            if item["score"] < 60
        ][:5]

        if strengths or weaknesses:
            return {
                "strengths": list(dict.fromkeys(strengths)),
                "weaknesses": list(dict.fromkeys(weaknesses)),
            }

        question_labels: dict[str, dict[str, float]] = {}
        for question in questions:
            label = (
                self._clean_label(question.get("domain"))
                or self._clean_label(question.get("primary_skill"))
                or self._clean_label(question.get("topic"))
            )
            if not label:
                continue
            stats = question_labels.setdefault(label, {"marks_obtained": 0.0, "full_marks": 0.0})
            stats["marks_obtained"] += float(question.get("marks_obtained") or 0)
            stats["full_marks"] += float(question.get("full_marks") or 0)

        derived = []
        for label, stats in question_labels.items():
            score = (stats["marks_obtained"] / stats["full_marks"] * 100) if stats["full_marks"] else 0.0
            derived.append({"label": label, "score": score})

        return {
            "strengths": [
                item["label"]
                for item in sorted(derived, key=lambda value: (value["score"], value["label"]), reverse=True)
                if item["score"] >= 70
            ][:5],
            "weaknesses": [
                item["label"]
                for item in sorted(derived, key=lambda value: (value["score"], value["label"]))
                if item["score"] < 60
            ][:5],
        }

    def _clean_label_list(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        labels = []
        for value in values:
            label = re.sub(r"\s+", " ", str(value or "")).strip()
            if self._is_placeholder_label(label):
                continue
            labels.append(label)
        return list(dict.fromkeys(labels))

    def _extract_json(self, response_text: str) -> str:
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        if cleaned.startswith("{"):
            return cleaned
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise json.JSONDecodeError("No JSON object found", response_text, 0)
        return match.group(0)

    def _normalize_question_item(self, item: dict[str, Any]) -> dict[str, Any]:
        rating = int(item.get("difficulty_rating") or 3)
        rating = max(1, min(5, rating))
        label = str(item.get("difficulty_label") or self._difficulty_label(rating)).strip().title()
        if label not in {"Easy", "Intermediate", "Hard"}:
            label = self._difficulty_label(rating)

        primary_skill = self._clean_label(item.get("primary_skill"))
        topic = self._clean_label(item.get("topic"))
        domain = self._clean_label(item.get("domain"))
        if primary_skill is None:
            primary_skill = topic or domain
        supporting_skills = [
            skill
            for skill in (self._clean_label(value) for value in item.get("supporting_skills", []))
            if skill and skill != primary_skill
        ][:2]

        return {
            "question_id": int(item.get("question_id") or 0),
            "domain": domain,
            "topic": topic,
            "primary_skill": primary_skill,
            "supporting_skills": supporting_skills,
            "difficulty_label": label,
            "difficulty_rating": rating,
            "mapping_source": "ai",
        }

    def _raise_for_missing_ai_labels(self, parsed: dict[str, Any]) -> None:
        bad_items = [
            {"question_id": item.get("question_id"), "errors": errors}
            for item in parsed.get("questions", [])
            if isinstance(item, dict)
            for errors in [self._label_errors(item)]
            if any(error.startswith("missing_") for error in errors)
        ]
        if bad_items:
            raise AIEnrichmentError(f"ChatGPT returned missing labels: {bad_items}")

    def _items_by_question_id(
        self,
        parsed: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> dict[int, dict[str, Any]]:
        items_by_id: dict[int, dict[str, Any]] = {}
        for index, item in enumerate(parsed.get("questions", [])):
            if not isinstance(item, dict):
                continue
            question_id = int(item.get("question_id") or 0)
            if not question_id and index < len(questions):
                question_id = int(questions[index].get("question_id") or 0)
                item["question_id"] = question_id
            if question_id:
                items_by_id[question_id] = item
        return items_by_id

    def _question_prompt_payload(self, question: dict[str, Any]) -> dict[str, Any]:
        return {
            "question_id": question.get("question_id"),
            "question_text": question.get("question_text"),
            "question_type": question.get("question_type"),
            "selected_answer": question.get("selected_answer"),
            "correct_answer": question.get("correct_answer"),
            "marks_obtained": question.get("marks_obtained", 0),
            "full_marks": question.get("full_marks", 0),
            "status": question.get("status"),
        }

    def _empty_question_item(self, question: dict[str, Any], source: str) -> dict[str, Any]:
        return {
            "question_id": int(question.get("question_id") or 0),
            "domain": None,
            "topic": None,
            "primary_skill": None,
            "supporting_skills": [],
            "difficulty_label": None,
            "difficulty_rating": None,
            "mapping_source": source,
        }

    def _label_errors(self, item: dict[str, Any]) -> list[str]:
        errors = []
        domain = str(item.get("domain") or "").strip()
        topic = str(item.get("topic") or "").strip()
        primary_skill = str(item.get("primary_skill") or "").strip()

        if self._is_placeholder_label(domain):
            errors.append("missing_domain")
        elif self._is_vague_domain(domain):
            errors.append("vague_domain")

        if self._is_placeholder_label(topic):
            errors.append("missing_topic")
        elif self._is_vague_topic(topic):
            errors.append("vague_topic")

        if self._is_placeholder_label(primary_skill):
            errors.append("missing_primary_skill")
        elif self._is_vague_topic(primary_skill):
            errors.append("vague_primary_skill")

        return errors

    def _is_vague_domain(self, value: str) -> bool:
        label = re.sub(r"\s+", " ", value).strip().lower()
        return label in VAGUE_DOMAIN_LABELS or len(label.split()) < 2

    def _is_vague_topic(self, value: str) -> bool:
        label = re.sub(r"\s+", " ", value).strip().lower()
        return label in VAGUE_TOPIC_LABELS

    def _clean_label(self, value: Any) -> str | None:
        label = re.sub(r"\s+", " ", str(value or "")).strip()
        if self._is_placeholder_label(label):
            return None
        return label

    def _is_placeholder_label(self, value: Any) -> bool:
        label = str(value or "").strip()
        return label in PLACEHOLDER_LABELS or label.lower() in PLACEHOLDER_LABELS

    def _difficulty_label(self, rating: int) -> str:
        if rating >= 4:
            return "Hard"
        if rating <= 2:
            return "Easy"
        return "Intermediate"
