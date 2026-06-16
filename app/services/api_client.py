from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.config import (
    ALL_CANDIDATE_ATTEMPTS_URL,
    APPLICATION_ID,
    CANDIDATE_DETAILS_URL, 
    CANDIDATE_ID,
    COURSE_EMAIL_ID,
    COURSE_LIST_URL,
    COURSE_USER_TYPE,
    CURRENT_CANDIDATE_PROFILE_URL,
    EXAM_ATTEMPT_URL,
    EXAM_ID,
    EXAM_METADATA_URL,
    EXAM_SUMMARY_URL,
    PORTAL_ID,
    TENANT_ID,
    USER_ID,
)


class LMSApiClient:
    def __init__(self) -> None:
        self.timeout = httpx.Timeout(30.0)

    async def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                return {
                    "url": url,
                    "params": params,
                    "ok": False,
                    "status_code": None,
                    "content_type": None,
                    "body": None,
                    "raw_text": "",
                    "error": str(exc),
                }

        raw_text = response.text
        content_type = response.headers.get("content-type", "")
        try:
            body = response.json()
        except ValueError:
            body = raw_text

        return {
            "url": url,
            "params": params,
            "ok": response.is_success,
            "status_code": response.status_code,
            "content_type": content_type,
            "body": body,
            "raw_text": raw_text,
            "error": None if response.is_success else raw_text,
        }

    def _extract_candidate(self, response: dict[str, Any]) -> dict[str, Any]:
        body = response.get("body")
        if isinstance(body, list):
            return body[0] if body else {}
        if isinstance(body, dict):
            candidates = body.get("value", [])
            return candidates[0] if candidates else {}
        return {}

    def _extract_summary(self, response: dict[str, Any], exam_id: int) -> dict[str, Any]:
        body = response.get("body")
        if isinstance(body, dict):
            for exam in body.get("data", []):
                if int(exam.get("ID", 0)) == exam_id:
                    return exam
        return {}

    def _extract_attempt(self, response: dict[str, Any]) -> dict[str, Any]:
        body = response.get("body")
        if isinstance(body, dict):
            attempts = body.get("data", [])
            return attempts[0] if attempts else {}
        return {}

    def _extract_course_list(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        body = response.get("body")
        if isinstance(body, list):
            return [item for item in body if isinstance(item, dict)]
        if isinstance(body, dict):
            data = body.get("data", [])
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        return []

    def _extract_candidate_profile(self, response: dict[str, Any]) -> dict[str, Any]:
        body = response.get("body")
        if isinstance(body, list):
            return {"sections": body}
        if isinstance(body, dict):
            return body
        return {}

    def _extract_all_candidate_attempts(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        body = response.get("body")
        if isinstance(body, dict):
            data = body.get("data", [])
        else:
            data = body

        if isinstance(data, str):
            stripped = data.strip()
            if not stripped or stripped == "{}":
                return []
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                return []

        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            nested = data.get("Candidates", data.get("data", data.get("items", [])))
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return []

    async def fetch_candidate_details_for(self, candidate_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        response = await self._request(
            CANDIDATE_DETAILS_URL,
            {"candidateId": candidate_id, "tenantId": TENANT_ID},
        )
        return self._extract_candidate(response), response

    async def fetch_candidate_profile_for(self, candidate_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        response = await self._request(
            CURRENT_CANDIDATE_PROFILE_URL,
            {"candidateId": candidate_id},
        )
        return self._extract_candidate_profile(response), response

    async def fetch_candidate_details(self) -> dict[str, Any]:
        details, _ = await self.fetch_candidate_details_for(CANDIDATE_ID)
        return details

    async def fetch_candidate_profile(self) -> dict[str, Any]:
        profile, _ = await self.fetch_candidate_profile_for(CANDIDATE_ID)
        return profile

    async def fetch_exam_summary(self, exam_id: int = EXAM_ID) -> dict[str, Any]:
        response = await self._request(
            EXAM_SUMMARY_URL,
            {
                "TenantID": TENANT_ID,
                "IDApplication": APPLICATION_ID,
            },
        )
        return self._extract_summary(response, exam_id)

    async def fetch_exam_attempt(self, exam_id: int = EXAM_ID) -> dict[str, Any]:
        response = await self._request(
            EXAM_ATTEMPT_URL,
            {
                "ExamID": exam_id,
                "TenantID": TENANT_ID,
                "IDApplication": APPLICATION_ID,
            },
        )
        return self._extract_attempt(response)

    async def fetch_course_list(self) -> list[dict[str, Any]]:
        response = await self._request(
            COURSE_LIST_URL,
            {
                "PortalID": PORTAL_ID,
                "TypeUser": COURSE_USER_TYPE,
                "EmailID": COURSE_EMAIL_ID,
                "TenantID": TENANT_ID.lower(),
            },
        )
        return self._extract_course_list(response)

    async def fetch_all_candidate_attempts(self, exam_id: int = EXAM_ID) -> list[dict[str, Any]]:
        response = await self._request(
            ALL_CANDIDATE_ATTEMPTS_URL,
            {
                "ExamID": exam_id,
                "TenantID": TENANT_ID,
                "IDApplication": APPLICATION_ID,
            },
        )
        extracted = self._extract_all_candidate_attempts(response)
        if isinstance(extracted, list):
            return extracted
        return []

    async def fetch_exam_metadata(self, exam_id: int = EXAM_ID) -> tuple[dict[str, Any], dict[str, Any]]:
        # The provided endpoint currently rejects documented params, so this is best-effort.
        candidates = [
            {"examId": exam_id, "userId": USER_ID},
            {"examId": exam_id, "userId": USER_ID, "TenantID": TENANT_ID},
            {"examId": exam_id, "UserId": USER_ID, "TenantID": TENANT_ID},
        ]
        for params in candidates:
            response = await self._request(EXAM_METADATA_URL, params)
            body = response.get("body")
            if isinstance(body, dict):
                return body, response
        return {}, response

    async def fetch_all(
        self,
        *,
        candidate_id: int | None = None,
        exam_id: int | None = None,
    ) -> dict[str, Any]:
        target_candidate_id = candidate_id or CANDIDATE_ID
        target_exam_id = exam_id or EXAM_ID
        candidate, candidate_profile, summary, attempt, metadata, course_list, all_candidate_attempts, raw_apis = (
            await self._gather_payloads(candidate_id=target_candidate_id, exam_id=target_exam_id)
        )
        candidate_ids = self._extract_candidate_ids(all_candidate_attempts)
        candidate_ids.add(target_candidate_id)
        candidate_records = await self._fetch_candidate_records(candidate_ids)
        return {
            "candidate": candidate,
            "candidate_profile": candidate_profile,
            "summary": summary,
            "attempt": attempt,
            "metadata": metadata,
            "course_list": course_list,
            "all_candidate_attempts": all_candidate_attempts,
            "candidate_records": candidate_records,
            "request_context": {
                "candidate_id": target_candidate_id,
                "exam_id": target_exam_id,
            },
            "raw_apis": raw_apis,
        }

    def _candidate_id_from_attempt_record(self, record: dict[str, Any]) -> int:
        value = (
            record.get("CandidateId")
            or record.get("Candidate_Id")
            or record.get("candidateId")
            or record.get("candidateid")
            or record.get("UserId")
        )
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _extract_candidate_ids(self, attempts: list[dict[str, Any]]) -> set[int]:
        candidate_ids: set[int] = set()
        for record in attempts:
            value = (
                record.get("CandidateId")
                or record.get("Candidate_Id")
                or record.get("candidateId")
                or record.get("candidateid")
            )
            try:
                candidate_id = int(value or 0)
            except (TypeError, ValueError):
                candidate_id = 0
            if candidate_id:
                candidate_ids.add(candidate_id)
        return candidate_ids

    async def _fetch_candidate_records(self, candidate_ids: set[int]) -> dict[str, Any]:
        records: dict[str, Any] = {}
        for candidate_id in sorted(candidate_ids):
            details, details_response = await self.fetch_candidate_details_for(candidate_id)
            profile, profile_response = await self.fetch_candidate_profile_for(candidate_id)
            records[str(candidate_id)] = {
                "candidate_id": candidate_id,
                "details": details,
                "profile": profile,
                "raw_apis": {
                    "candidate_details": details_response,
                    "candidate_profile": profile_response,
                },
            }
        return records

    async def _gather_payloads(self, *, candidate_id: int, exam_id: int) -> tuple[dict[str, Any], ...]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            candidate_task = client.get(
                CANDIDATE_DETAILS_URL,
                params={"candidateId": candidate_id, "tenantId": TENANT_ID},
            )
            candidate_profile_task = client.get(
                CURRENT_CANDIDATE_PROFILE_URL,
                params={"candidateId": candidate_id},
            )
            summary_task = client.get(
                EXAM_SUMMARY_URL,
                params={"TenantID": TENANT_ID, "IDApplication": APPLICATION_ID},
            )
            attempt_task = client.get(
                EXAM_ATTEMPT_URL,
                params={
                    "ExamID": exam_id,
                    "TenantID": TENANT_ID,
                    "IDApplication": APPLICATION_ID,
                },
            )
            course_list_task = client.get(
                COURSE_LIST_URL,
                params={
                    "PortalID": PORTAL_ID,
                    "TypeUser": COURSE_USER_TYPE,
                    "EmailID": COURSE_EMAIL_ID,
                    "TenantID": TENANT_ID.lower(),
                },
            )
            all_candidate_attempts_task = client.get(
                ALL_CANDIDATE_ATTEMPTS_URL,
                params={
                    "ExamID": exam_id,
                    "TenantID": TENANT_ID,
                    "IDApplication": APPLICATION_ID,
                },
            )

            (
                candidate_response,
                candidate_profile_response,
                summary_response,
                attempt_response,
                course_list_response,
                all_candidate_attempts_response,
            ) = await asyncio.gather(
                candidate_task,
                candidate_profile_task,
                summary_task,
                attempt_task,
                course_list_task,
                all_candidate_attempts_task,
            )

        candidate_payload = {
            "url": str(candidate_response.url),
            "params": {"candidateId": candidate_id, "tenantId": TENANT_ID},
            "ok": candidate_response.is_success,
            "status_code": candidate_response.status_code,
            "content_type": candidate_response.headers.get("content-type", ""),
            "body": self._coerce_body(candidate_response),
            "raw_text": candidate_response.text,
            "error": None if candidate_response.is_success else candidate_response.text,
        }
        candidate_profile_payload = {
            "url": str(candidate_profile_response.url),
            "params": {"candidateId": candidate_id},
            "ok": candidate_profile_response.is_success,
            "status_code": candidate_profile_response.status_code,
            "content_type": candidate_profile_response.headers.get("content-type", ""),
            "body": self._coerce_body(candidate_profile_response),
            "raw_text": candidate_profile_response.text,
            "error": None if candidate_profile_response.is_success else candidate_profile_response.text,
        }
        summary_payload = {
            "url": str(summary_response.url),
            "params": {"TenantID": TENANT_ID, "IDApplication": APPLICATION_ID},
            "ok": summary_response.is_success,
            "status_code": summary_response.status_code,
            "content_type": summary_response.headers.get("content-type", ""),
            "body": self._coerce_body(summary_response),
            "raw_text": summary_response.text,
            "error": None if summary_response.is_success else summary_response.text,
        }
        attempt_payload = {
            "url": str(attempt_response.url),
            "params": {
                "ExamID": exam_id,
                "TenantID": TENANT_ID,
                "IDApplication": APPLICATION_ID,
            },
            "ok": attempt_response.is_success,
            "status_code": attempt_response.status_code,
            "content_type": attempt_response.headers.get("content-type", ""),
            "body": self._coerce_body(attempt_response),
            "raw_text": attempt_response.text,
            "error": None if attempt_response.is_success else attempt_response.text,
        }
        course_list_payload = {
            "url": str(course_list_response.url),
            "params": {
                "PortalID": PORTAL_ID,
                "TypeUser": COURSE_USER_TYPE,
                "EmailID": COURSE_EMAIL_ID,
                "TenantID": TENANT_ID.lower(),
            },
            "ok": course_list_response.is_success,
            "status_code": course_list_response.status_code,
            "content_type": course_list_response.headers.get("content-type", ""),
            "body": self._coerce_body(course_list_response),
            "raw_text": course_list_response.text,
            "error": None if course_list_response.is_success else course_list_response.text,
        }
        all_candidate_attempts_payload = {
            "url": str(all_candidate_attempts_response.url),
            "params": {
                "ExamID": exam_id,
                "TenantID": TENANT_ID,
                "IDApplication": APPLICATION_ID,
            },
            "ok": all_candidate_attempts_response.is_success,
            "status_code": all_candidate_attempts_response.status_code,
            "content_type": all_candidate_attempts_response.headers.get("content-type", ""),
            "body": self._coerce_body(all_candidate_attempts_response),
            "raw_text": all_candidate_attempts_response.text,
            "error": None if all_candidate_attempts_response.is_success else all_candidate_attempts_response.text,
        }
        metadata, metadata_payload = await self.fetch_exam_metadata(exam_id)

        return (
            self._extract_candidate(candidate_payload),
            self._extract_candidate_profile(candidate_profile_payload),
            self._extract_summary(summary_payload, exam_id),
            self._extract_attempt(attempt_payload),
            metadata,
            self._extract_course_list(course_list_payload),
            self._extract_all_candidate_attempts(all_candidate_attempts_payload),
            {
                "candidate_details": candidate_payload,
                "candidate_profile": candidate_profile_payload,
                "exam_summary": summary_payload,
                "exam_attempt_answer": attempt_payload,
                "exam_metadata": metadata_payload,
                "course_list": course_list_payload,
                "all_candidate_attempts": all_candidate_attempts_payload,
            },
        )

    def _coerce_body(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text
