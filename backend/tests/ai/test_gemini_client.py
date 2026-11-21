"""Gemini client: request shape, reply parsing and error mapping (no network)."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.modules.ai.client import AiReplyFormatError, GeminiClient, parse_json_reply
from app.modules.ai.deps import AiRateLimiter
from app.shared.errors.exceptions import AiFailedError, AiRateLimitedError, AiRejectedError


def _client(handler) -> tuple[GeminiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(_wrapped))
    return GeminiClient("test-key-not-real", "test-model", http), seen


def _reply(text: str, finish: str = "STOP") -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}]})


def test_request_uses_header_key_and_model():
    client, seen = _client(lambda _: _reply('{"ok": true}'))
    assert asyncio.run(client.generate_json("نظام", "طلب")) == {"ok": True}
    req = seen[0]
    assert req.url.path.endswith("/models/test-model:generateContent")
    assert req.headers["x-goog-api-key"] == "test-key-not-real"
    assert "key=" not in str(req.url)  # never in the URL, so it can't leak into logs
    body = json.loads(req.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "نظام"
    assert body["contents"][0]["parts"][0]["text"] == "طلب"


@pytest.mark.parametrize(
    "text",
    ['{"a": 1}', '```json\n{"a": 1}\n```', 'هذا هو الرد:\n{"a": 1}\nانتهى'],
)
def test_lenient_json_parsing(text):
    assert parse_json_reply(text) == {"a": 1}


@pytest.mark.parametrize("text", ["", "لا يوجد", "{bad json}"])
def test_unparseable_reply(text):
    with pytest.raises(AiReplyFormatError):
        parse_json_reply(text)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429, json={}), AiRateLimitedError),
        (httpx.Response(400, json={"error": {"message": "API key not valid"}}), AiFailedError),
        (httpx.Response(500, json={}), AiFailedError),
        (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), AiRejectedError),
        (_reply("", finish="SAFETY"), AiRejectedError),
        (httpx.Response(200, json={"candidates": []}), AiFailedError),
    ],
)
def test_error_mapping(response, error):
    client, _ = _client(lambda _: response)
    with pytest.raises(error):
        asyncio.run(client.generate_json("s", "p"))


def test_network_failure_is_ai_failed():
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    client, _ = _client(boom)
    with pytest.raises(AiFailedError):
        asyncio.run(client.generate_json("s", "p"))


def test_rate_limiter_is_per_teacher():
    limiter = AiRateLimiter(limit=2)
    a, b = uuid4(), uuid4()
    limiter.check(a)
    limiter.check(a)
    with pytest.raises(AiRateLimitedError):
        limiter.check(a)
    limiter.check(b)


def test_blank_key_means_ai_disabled():
    s = Settings(supabase_url="https://x.supabase.co", database_url="postgresql://u:p@h/d", gemini_api_key="  ")
    assert s.gemini_api_key is None


def test_app_builds_gemini_client_only_with_a_key():
    base = {"supabase_url": "https://x.supabase.co", "database_url": "postgresql://u:p@h/d", "app_env": "test"}
    with TestClient(create_app(Settings(**base, gemini_api_key="test-key-not-real"), connect_db=False)) as c:
        assert isinstance(c.app.state.ai_client, GeminiClient)
    with TestClient(create_app(Settings(**base), connect_db=False)) as c:
        assert c.app.state.ai_client is None
