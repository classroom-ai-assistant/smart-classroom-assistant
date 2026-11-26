"""Listening: short answer recordings -> text with OpenAI speech-to-text.

Internship prototype (approved 2026-11-26): tested with the team's own
voices, no real children. The audio is sent once, never stored or logged,
and the transcript is never logged either. Before any use with real
children this must be reviewed again (OpenAI requires Zero Data Retention
for personal data of children under 13, or move listening on-device).
"""

import logging
from typing import Protocol

import httpx

from app.shared.errors.exceptions import AiBusyError, AiFailedError, AiRateLimitedError

logger = logging.getLogger("app.listening")

API_URL = "https://api.openai.com/v1/audio/transcriptions"
_TRANSIENT = {500, 502, 503, 504}
_EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav",
        "audio/mp4": "m4a", "audio/mpeg": "mp3"}


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime: str, keywords: list[str]) -> str: ...


class OpenAiTranscriber:
    def __init__(self, api_key: str, model: str, http: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._model = model
        self._http = http

    async def _post(self, audio: bytes, mime: str, data: dict) -> httpx.Response:
        try:
            return await self._http.post(
                API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files={"file": (f"answer.{_EXT.get(mime, 'webm')}", audio, mime)},
                data=data,
            )
        except httpx.HTTPError as exc:
            logger.warning("openai transcription network error: %s", type(exc).__name__)
            raise AiBusyError() from exc

    async def transcribe(self, audio: bytes, mime: str, keywords: list[str]) -> str:
        data: dict = {"model": self._model, "response_format": "json", "languages[]": ["ar"]}
        if keywords:
            data["keywords[]"] = keywords
        response = await self._post(audio, mime, data)
        if response.status_code == 400:
            # Older parameter set: one language + a prompt carrying the expected words.
            self._log(response)
            plain = {"model": self._model, "response_format": "json", "language": "ar"}
            if keywords:
                plain["prompt"] = "، ".join(keywords)
            response = await self._post(audio, mime, plain)
        if response.status_code == 429:
            self._log(response)
            raise AiRateLimitedError()
        if response.status_code in _TRANSIENT:
            self._log(response)
            raise AiBusyError()
        if response.status_code != 200:
            self._log(response)
            raise AiFailedError()
        try:
            return str(response.json().get("text") or "").strip()
        except ValueError as exc:
            raise AiFailedError() from exc

    @staticmethod
    def _log(response: httpx.Response) -> None:
        try:
            err = response.json().get("error") or {}
            detail = f"type={err.get('type')} code={err.get('code')} message={str(err.get('message'))[:200]}"
        except ValueError:
            detail = "no json body"
        logger.warning("openai transcription HTTP %s %s", response.status_code, detail)
