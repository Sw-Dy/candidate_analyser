from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.config import (
    APPLICATION_ID,
    CANDIDATE_DETAILS_URL,
    CANDIDATE_ID,
    EXAM_ATTEMPT_URL,
    EXAM_ID,
    EXAM_METADATA_URL,
    EXAM_SUMMARY_URL,
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

    def _extract_summary(self, response: dict[str, Any]) -> dict[str, Any]:
        body = response.get("body")
        if isinstance(body, dict):
            for exam in body.get("data", []):
                if int(exam.get("ID", 0)) == EXAM_ID:
                    return exam
        return {}

    def _extract_attempt(self, response: dict[str, Any]) -> dict[str, Any]:
        body = response.get("body")
        if isinstance(body, dict):
            attempts = body.get("data", [])
            return attempts[0] if attempts else {}
        return {}

    async def fetch_candidate_details(self) -> dict[str, Any]:
        response = await self._request(
            CANDIDATE_DETAILS_URL,
            {"candidateId": CANDIDATE_ID},
        )
        return self._extract_candidate(response)

    async def fetch_exam_summary(self) -> dict[str, Any]:
        response = await self._request(
            EXAM_SUMMARY_URL,
            {
                "TenantID": TENANT_ID,
                "IDApplication": APPLICATION_ID,
            },
        )
        return self._extract_summary(response)

    async def fetch_exam_attempt(self) -> dict[str, Any]:
        response = await self._request(
            EXAM_ATTEMPT_URL,
            {
                "ExamID": EXAM_ID,
                "TenantID": TENANT_ID,
                "IDApplication": APPLICATION_ID,
            },
        )
        return self._extract_attempt(response)

    async def fetch_exam_metadata(self) -> tuple[dict[str, Any], dict[str, Any]]:
        # The provided endpoint currently rejects documented params, so this is best-effort.
        candidates = [
            {"examId": EXAM_ID, "userId": USER_ID},
            {"examId": EXAM_ID, "userId": USER_ID, "TenantID": TENANT_ID},
            {"examId": EXAM_ID, "UserId": USER_ID, "TenantID": TENANT_ID},
        ]
        for params in candidates:
            response = await self._request(EXAM_METADATA_URL, params)
            body = response.get("body")
            if isinstance(body, dict):
                return body, response
        return {}, response

    async def fetch_all(self) -> dict[str, Any]:
        candidate, summary, attempt, metadata, raw_apis = await self._gather_payloads()
        return {
            "candidate": candidate,
            "summary": summary,
            "attempt": attempt,
            "metadata": metadata,
            "raw_apis": raw_apis,
        }

    async def _gather_payloads(self) -> tuple[dict[str, Any], ...]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            candidate_task = client.get(
                CANDIDATE_DETAILS_URL,
                params={"candidateId": CANDIDATE_ID},
            )
            summary_task = client.get(
                EXAM_SUMMARY_URL,
                params={"TenantID": TENANT_ID, "IDApplication": APPLICATION_ID},
            )
            attempt_task = client.get(
                EXAM_ATTEMPT_URL,
                params={
                    "ExamID": EXAM_ID,
                    "TenantID": TENANT_ID,
                    "IDApplication": APPLICATION_ID,
                },
            )

            candidate_response, summary_response, attempt_response = await asyncio.gather(
                candidate_task,
                summary_task,
                attempt_task,
            )

        candidate_payload = {
            "url": str(candidate_response.url),
            "params": {"candidateId": CANDIDATE_ID},
            "ok": candidate_response.is_success,
            "status_code": candidate_response.status_code,
            "content_type": candidate_response.headers.get("content-type", ""),
            "body": self._coerce_body(candidate_response),
            "raw_text": candidate_response.text,
            "error": None if candidate_response.is_success else candidate_response.text,
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
                "ExamID": EXAM_ID,
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
        metadata, metadata_payload = await self.fetch_exam_metadata()

        return (
            self._extract_candidate(candidate_payload),
            self._extract_summary(summary_payload),
            self._extract_attempt(attempt_payload),
            metadata,
            {
                "candidate_details": candidate_payload,
                "exam_summary": summary_payload,
                "exam_attempt_answer": attempt_payload,
                "exam_metadata": metadata_payload,
            },
        )

    def _coerce_body(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text
