"""Robot voice PoC: Gemini TTS client and the /api/v1/speech endpoint (no network)."""

import asyncio
import base64
import json

import httpx
import pytest

from app.modules.ai.deps import AiRateLimiter
from app.modules.speech.client import GeminiSpeechClient, pcm_to_wav
from app.shared.errors.exceptions import AiBusyError, AiFailedError

PCM = b"\x00\x01" * 2400  # 0.1 s of 24 kHz mono 16-bit


def _audio_reply(raw: bytes) -> httpx.Response:
    data = base64.b64encode(raw).decode()
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"data": data}}]}}]})


def _client(handler, fallback=None):
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return GeminiSpeechClient("test-key-not-real", "tts-model", http, fallback_model=fallback), seen


def test_request_shape_and_raw_pcm_is_wrapped_as_wav():
    client, seen = _client(lambda _: _audio_reply(PCM))
    audio = asyncio.run(client.synthesize("واحد، اثنان، ثلاثة", "Puck"))
    assert audio[:4] == b"RIFF" and audio.endswith(PCM)
    body = json.loads(seen[0].content)
    assert body["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert body["generationConfig"]["speechConfig"]["voiceConfig"]["voice"] == "Puck"
    assert body["contents"][0]["parts"][0]["text"] == "واحد، اثنان، ثلاثة"
    assert seen[0].headers["x-goog-api-key"] == "test-key-not-real"


def test_wav_reply_is_passed_through():
    wav = pcm_to_wav(PCM)
    client, _ = _client(lambda _: _audio_reply(wav))
    assert asyncio.run(client.synthesize("مرحبا", "Kore")) == wav


def test_overloaded_model_falls_back():
    def handler(request: httpx.Request) -> httpx.Response:
        if "tts-model:" in request.url.path:
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})
        return _audio_reply(PCM)

    client, seen = _client(handler, fallback="lite-tts")
    assert asyncio.run(client.synthesize("مرحبا", "Puck"))[:4] == b"RIFF"
    assert len(seen) == 2


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503, json={}), AiBusyError),
        (httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}}), AiFailedError),
        (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "no audio"}]}}]}), AiFailedError),
    ],
)
def test_errors(response, error):
    client, _ = _client(lambda _: response)
    with pytest.raises(error):
        asyncio.run(client.synthesize("مرحبا", "Puck"))


class FakeSpeech:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text: str, voice: str) -> bytes:
        self.calls.append((text, voice))
        return pcm_to_wav(PCM)


@pytest.fixture
def speech(app):
    fake = FakeSpeech()
    app.state.speech_client = fake
    return fake


def test_endpoint_returns_wav(client, auth_headers, speech):
    r = client.post("/api/v1/speech", headers=auth_headers, json={"text": " قصة الفراشة ", "voice": "Leda"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"
    assert r.headers["cache-control"] == "no-store"
    assert speech.calls == [("قصة الفراشة", "Leda")]


def test_default_voice(client, auth_headers, speech):
    assert client.post("/api/v1/speech", headers=auth_headers, json={"text": "مرحبا"}).status_code == 200
    assert speech.calls[0][1] == "Puck"


@pytest.mark.parametrize(
    "body", [{"text": ""}, {"text": "x" * 3001}, {"text": "مرحبا", "voice": "Unknown"}, {"text": "مرحبا", "child": "سارة"}]
)
def test_invalid_requests(client, auth_headers, speech, body):
    assert client.post("/api/v1/speech", headers=auth_headers, json=body).status_code == 422
    assert speech.calls == []


def test_requires_token(client, speech):
    assert client.post("/api/v1/speech", json={"text": "مرحبا"}).status_code == 401


def test_without_key_is_503(client, auth_headers):
    r = client.post("/api/v1/speech", headers=auth_headers, json={"text": "مرحبا"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"


def test_rate_limited(client, app, auth_headers, speech):
    app.state.speech_limiter = AiRateLimiter(limit=1)
    assert client.post("/api/v1/speech", headers=auth_headers, json={"text": "مرحبا"}).status_code == 200
    assert client.post("/api/v1/speech", headers=auth_headers, json={"text": "مرحبا"}).status_code == 429
