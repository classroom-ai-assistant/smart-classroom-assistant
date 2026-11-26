"""Live call: the backend mints a short-lived OpenAI Realtime secret with the
robot's instructions. OpenAI is mocked; database tests use local Postgres."""

import json

import httpx
import pytest

from app.modules.listening.live import CALLS_URL, LiveConfig, live_instructions
from tests.db.fixtures import requires_db

SLIDES = [
    {"layout": {"elements": [{"type": "text", "text": "حرف الباء"}]}, "question": None},
    {"layout": {"elements": [{"type": "sticker", "name": "duck"}]}, "question": {"question": "ما أول حرف في بطة؟"}},
]


def test_instructions_have_persona_deck_current_slide_and_safety():
    text = live_instructions({"title": "حرف الباء", "topic": "الحروف", "age_group": "age_4_5"},
                             {"robot_name": "نجمة", "robot_style": "calm"}, SLIDES, 1)
    assert "«نجمة»" in text and "هادئ" in text and "4 إلى 5 سنوات" in text
    assert "شريحة 1: نص: حرف الباء" in text and "▶ شريحة 2" in text and "رقم 2" in text
    assert "لا تسأل أي طفل عن اسمه" in text and "لا تدّعِ أنك إنسان" in text


def test_live_config_never_shows_the_key():
    assert "sk-secret" not in repr(LiveConfig(api_key="sk-secret", model="m", voice="marin"))


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. لمى")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


def _lesson_with_slide(client, h):
    lesson = client.post("/api/v1/lessons", headers=h, json={"title": "حرف الباء", "topic": "الحروف", "age_group": "age_4_5"}).json()
    s = client.post(f"/api/v1/lessons/{lesson['id']}/slides", headers=h, json={
        "layout": {"elements": [{"id": "t", "type": "text", "text": "بطة", "x": 1, "y": 1, "w": 50, "h": 20}]}}).json()
    return lesson["id"], s["id"]


def _openai(handler):
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(wrapped)), seen


@pytest.mark.integration
@requires_db
def test_live_session_mints_secret_with_instructions(db_client, teacher):
    h = teacher["headers"]
    db_client.patch("/api/v1/me/settings", headers=h, json={"robot_name": "نجمة"})
    lid, sid = _lesson_with_slide(db_client, h)
    http, seen = _openai(lambda r: httpx.Response(200, json={
        "value": "ek_test", "expires_at": 1890000000, "session": {"audio": {"output": {"voice": "marin"}}}}))
    db_client.app.state.live_config = LiveConfig(api_key="sk-test-not-real", model="gpt-realtime-2.1-mini", voice="marin")
    db_client.app.state.live_http = http

    r = db_client.post(f"/api/v1/lessons/{lid}/live-session?slide_id={sid}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"client_secret": "ek_test", "expires_at": 1890000000, "model": "gpt-realtime-2.1-mini",
                        "voice": "marin", "calls_url": CALLS_URL}
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/realtime/client_secrets"
    assert req.headers["authorization"] == "Bearer sk-test-not-real"
    body = json.loads(req.content)
    assert body["expires_after"] == {"anchor": "created_at", "seconds": 600}
    assert body["session"]["type"] == "realtime" and body["session"]["model"] == "gpt-realtime-2.1-mini"
    assert body["session"]["audio"]["output"]["voice"] == "marin"
    assert "«نجمة»" in body["session"]["instructions"] and "▶ شريحة 1" in body["session"]["instructions"]
    assert "sk-test-not-real" not in r.text


@pytest.mark.integration
@requires_db
def test_live_session_retries_without_audio_options_then_errors(db_client, teacher, make_teacher, make_token):
    h = teacher["headers"]
    lid, _ = _lesson_with_slide(db_client, h)
    assert db_client.post(f"/api/v1/lessons/{lid}/live-session", headers=h).status_code == 503  # no key

    def handler(r):
        if "audio" in json.loads(r.content)["session"]:
            return httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "bad audio"}})
        return httpx.Response(200, json={"value": "ek_2", "expires_at": 1})

    http, seen = _openai(handler)
    db_client.app.state.live_config = LiveConfig(api_key="k", model="m", voice="marin")
    db_client.app.state.live_http = http
    r = db_client.post(f"/api/v1/lessons/{lid}/live-session", headers=h)
    assert r.status_code == 200 and r.json()["client_secret"] == "ek_2" and len(seen) == 2

    db_client.app.state.live_http, _ = _openai(lambda r: httpx.Response(429, json={}))
    assert db_client.post(f"/api/v1/lessons/{lid}/live-session", headers=h).status_code == 429
    db_client.app.state.live_http, _ = _openai(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    assert db_client.post(f"/api/v1/lessons/{lid}/live-session", headers=h).status_code == 502

    other = {"Authorization": f"Bearer {make_token(make_teacher('أ. هند'))}"}
    assert db_client.post(f"/api/v1/lessons/{lid}/live-session", headers=other).status_code == 404
    from uuid import uuid4
    assert db_client.post(f"/api/v1/lessons/{lid}/live-session?slide_id={uuid4()}", headers=h).status_code == 404
