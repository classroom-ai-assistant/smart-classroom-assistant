"""Robot voice: Gemini text-to-speech over REST (voice PoC, slice 5 preview).

Input is lesson text written or approved by the teacher; nothing about the
children is sent. Audio is returned to the browser and never stored.
"""

import base64
import io
import logging
import wave
from typing import Protocol

import httpx

from app.modules.ai.client import API_BASE
from app.shared.errors.exceptions import AiBusyError, AiFailedError, AiRateLimitedError, AiRejectedError

logger = logging.getLogger("app.speech")

# Gemini TTS returns 24 kHz, mono, 16-bit PCM (WAV for unary calls).
SAMPLE_RATE = 24_000
_TRANSIENT = {500, 502, 503, 504}

# Voices offered for the PoC comparison; Lama picks the robot's voice from these.
VOICES = ("Puck", "Kore", "Leda", "Achird", "Sulafat", "Zephyr")
DEFAULT_STYLE = "بصوت دافئ ومرح وواضح، وببطء مناسب لأطفال الروضة"


class SpeechClient(Protocol):
    async def synthesize(self, text: str, voice: str) -> bytes: ...


def pcm_to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


class GeminiSpeechClient:
    def __init__(self, api_key: str, model: str, http: httpx.AsyncClient, fallback_model: str | None = None) -> None:
        self._api_key = api_key
        self._models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
        self._http = http

    async def synthesize(self, text: str, voice: str) -> bytes:
        body = {
            "contents": [{"role": "user", "parts": [{"text": text, "speech_metadata": {"style": DEFAULT_STYLE}}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"voice": voice}},
            },
        }
        for model in self._models:
            try:
                response = await self._http.post(
                    f"{API_BASE}/models/{model}:generateContent",
                    json=body,
                    headers={"x-goog-api-key": self._api_key},
                )
            except httpx.HTTPError as exc:
                logger.warning("gemini tts request failed model=%s: %s", model, type(exc).__name__)
                continue
            if response.status_code in _TRANSIENT:
                self._log_error(response, model)
                continue
            return self._read(response, model)
        raise AiBusyError()

    @staticmethod
    def _log_error(response: httpx.Response, model: str) -> None:
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        logger.warning(
            "gemini tts returned HTTP %s model=%s status=%s message=%s",
            response.status_code,
            model,
            error.get("status"),
            str(error.get("message", ""))[:200],
        )

    def _read(self, response: httpx.Response, model: str) -> bytes:
        if response.status_code == 429:
            self._log_error(response, model)
            raise AiRateLimitedError("خدمة الصوت وصلت حدّها، حاولي بعد قليل")
        if response.status_code != 200:
            self._log_error(response, model)
            raise AiFailedError("تعذّر تجهيز الصوت الآن، حاولي مرة أخرى")
        data = response.json()
        if data.get("promptFeedback", {}).get("blockReason"):
            raise AiRejectedError()
        try:
            part = data["candidates"][0]["content"]["parts"][0]
            audio = base64.b64decode(part["inlineData"]["data"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("gemini tts reply had no audio model=%s", model)
            raise AiFailedError("تعذّر تجهيز الصوت الآن، حاولي مرة أخرى") from exc
        return audio if audio[:4] == b"RIFF" else pcm_to_wav(audio)
