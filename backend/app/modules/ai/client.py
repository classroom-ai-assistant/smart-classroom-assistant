"""Gemini text generation over REST (slice 3, FR-016 to FR-021).

Only lesson data written by the teacher is sent (title, topic, age group,
her notes or her draft). No child data ever reaches this module.

The model is asked for JSON in the prompt and the reply is parsed leniently;
callers validate the result against the activity schemas.
"""

import json
import logging
import re
from typing import Any, Protocol

import httpx

from app.shared.errors.exceptions import AiFailedError, AiRateLimitedError, AiRejectedError

logger = logging.getLogger("app.ai")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class AiClient(Protocol):
    async def generate_json(self, system: str, prompt: str) -> Any: ...


class AiReplyFormatError(Exception):
    """The model answered, but not with parseable JSON."""


def parse_json_reply(text: str) -> Any:
    """Accept bare JSON, fenced JSON, or JSON surrounded by stray text."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AiReplyFormatError("no JSON object in reply") from None
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AiReplyFormatError("invalid JSON in reply") from exc


class GeminiClient:
    def __init__(self, api_key: str, model: str, http: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._model = model
        self._http = http

    async def generate_json(self, system: str, prompt: str) -> Any:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.8},
        }
        try:
            response = await self._http.post(
                f"{API_BASE}/models/{self._model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self._api_key},
            )
        except httpx.HTTPError as exc:
            logger.warning("gemini request failed: %s", type(exc).__name__)
            raise AiFailedError() from exc

        if response.status_code == 429:
            raise AiRateLimitedError("خدمة الذكاء مشغولة أو وصلت حدّها، حاولي بعد قليل")
        if response.status_code != 200:
            # Google's error status/message (e.g. API_KEY_INVALID, model NOT_FOUND)
            # says what is wrong; it never contains the key or our prompt.
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {}
            logger.warning(
                "gemini returned HTTP %s model=%s status=%s message=%s",
                response.status_code,
                self._model,
                error.get("status"),
                str(error.get("message", ""))[:200],
            )
            raise AiFailedError()

        data = response.json()
        if data.get("promptFeedback", {}).get("blockReason"):
            raise AiRejectedError()
        candidates = data.get("candidates") or []
        if not candidates:
            raise AiFailedError()
        candidate = candidates[0]
        if candidate.get("finishReason") in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}:
            raise AiRejectedError()
        text = "".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", []))
        return parse_json_reply(text)
