"""Listening to answers: matching, the OpenAI client (mocked HTTP) and the
endpoint on the local Postgres. No real audio or network."""

import asyncio
from typing import Any

import httpx
import pytest

from app.modules.listening.client import OpenAiTranscriber
from app.modules.listening.matching import match, normalize
from app.shared.errors.exceptions import AiBusyError, AiRateLimitedError
from tests.db.fixtures import requires_db

AUDIO = b"\x1aE\xdf\xa3" + b"\x00" * 400  # looks like a short webm, content is irrelevant


# ------------------------------------------------------------- matching
@pytest.mark.parametrize(
    ("heard", "expected", "found"),
    [
        ("الباء!", ["باء"], "باء"),
        ("بَاء", ["باء"], "باء"),
        ("هي تفاحة حمراء", ["تفاحه", "موز"], "تفاحه"),
        ("3", ["ثلاثة"], "ثلاثة"),
        ("٣ تفاحات", ["ثلاث"], "ثلاث"),
        ("أرنب", ["ارنب"], "ارنب"),
        ("قطة", ["كلب"], None),
        ("موزة", ["موز"], None),  # whole words only
        ("", ["باء"], None),
    ],
)
def test_match(heard, expected, found):
    assert match(heard, expected) == found


def test_normalize_handles_forms():
    assert normalize("إلى المدرسةِ") == ["الي", "مدرسه"]


# ------------------------------------------------------------- client
def _client(handler) -> OpenAiTranscriber:
    return OpenAiTranscriber("test-key-not-real", "gpt-transcribe", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_client_sends_model_language_keywords():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": " باء "})

    text = asyncio.run(_client(handler).transcribe(AUDIO, "audio/webm", ["باء", "ب"]))
    assert text == "باء"
    req = seen[0]
    body = req.content.decode("utf-8", "ignore")
    assert req.url == "https://api.openai.com/v1/audio/transcriptions"
    assert req.headers["authorization"] == "Bearer test-key-not-real"
    assert 'name="model"' in body and "gpt-transcribe" in body
    assert 'name="keywords[]"' in body and body.count('name="keywords[]"') == 2
    assert 'filename="answer.webm"' in body


def test_client_falls_back_when_parameters_rejected():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", "ignore")
        calls.append(body)
        if "keywords[]" in body:
            return httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "unknown param"}})
        return httpx.Response(200, json={"text": "تفاحة"})

    assert asyncio.run(_client(handler).transcribe(AUDIO, "audio/webm", ["تفاحة"])) == "تفاحة"
    assert len(calls) == 2 and 'name="language"' in calls[1] and 'name="prompt"' in calls[1]


@pytest.mark.parametrize(("status", "error"), [(429, AiRateLimitedError), (503, AiBusyError)])
def test_client_errors(status, error):
    with pytest.raises(error):
        asyncio.run(_client(lambda r: httpx.Response(status, json={})).transcribe(AUDIO, "audio/webm", []))


# ------------------------------------------------------------- endpoint
class FakeTranscriber:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls: list[dict[str, Any]] = []

    async def transcribe(self, audio, mime, keywords):
        self.calls.append({"size": len(audio), "mime": mime, "keywords": keywords})
        return self.texts.pop(0)


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. لمى")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


def _slide(client, h, question):
    lesson = client.post("/api/v1/lessons", headers=h, json={"title": "حرف الباء", "topic": "الحروف", "age_group": "age_4_5"}).json()
    body = {"layout": {"elements": []}}
    if question:
        body["question"] = question
    s = client.post(f"/api/v1/lessons/{lesson['id']}/slides", headers=h, json=body).json()
    return f"/api/v1/lessons/{lesson['id']}/slides/{s['id']}/listen"


Q = {"question": "ما أول حرف في بطة؟", "expected_answers": ["باء", "ب"], "hint": "اسمعوا: بـ بـ بطة", "simpler_question": "بطة تبدأ بحرف الباء؟"}


@pytest.mark.integration
@requires_db
def test_listen_correct_wrong_silent(db_client, teacher):
    h = {**teacher["headers"], "Content-Type": "audio/webm"}
    url = _slide(db_client, teacher["headers"], Q)
    fake = FakeTranscriber("الباء", "تاء", "")
    db_client.app.state.transcriber = fake

    r = db_client.post(url, headers=h, content=AUDIO)
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "correct" and r.json()["matched"] == "باء"
    assert fake.calls[0] == {"size": len(AUDIO), "mime": "audio/webm", "keywords": ["باء", "ب"]}

    r = db_client.post(url, headers=h, content=AUDIO).json()
    assert r["result"] == "wrong" and r["hint"] == Q["hint"] and r["heard"] == "تاء"

    r = db_client.post(url, headers=h, content=AUDIO).json()
    assert r["result"] == "silent" and r["simpler_question"] == Q["simpler_question"]


@pytest.mark.integration
@requires_db
def test_listen_without_question_just_hears(db_client, teacher):
    url = _slide(db_client, teacher["headers"], None)
    db_client.app.state.transcriber = FakeTranscriber("نعم فهمنا")
    r = db_client.post(url, headers={**teacher["headers"], "Content-Type": "audio/ogg"}, content=AUDIO)
    assert r.status_code == 200 and r.json() == {"result": "heard", "heard": "نعم فهمنا", "matched": None,
                                                 "hint": None, "simpler_question": None}


@pytest.mark.integration
@requires_db
def test_listen_rejections(db_client, teacher, make_teacher, make_token):
    url = _slide(db_client, teacher["headers"], Q)
    h = {**teacher["headers"], "Content-Type": "audio/webm"}
    # no key configured -> 503
    assert db_client.post(url, headers=h, content=AUDIO).status_code == 503
    fake = FakeTranscriber()
    db_client.app.state.transcriber = fake
    assert db_client.post(url, headers={**teacher["headers"], "Content-Type": "text/plain"}, content=AUDIO).status_code == 422
    assert db_client.post(url, headers=h, content=b"x").json()["error"]["details"][0]["type"] == "empty"
    big = db_client.post(url, headers=h, content=b"\x00" * (2 * 1024 * 1024 + 1))
    assert big.status_code == 422 and big.json()["error"]["details"][0]["type"] == "too_large"
    other = {"Authorization": f"Bearer {make_token(make_teacher('أ. هند'))}", "Content-Type": "audio/webm"}
    assert db_client.post(url, headers=other, content=AUDIO).status_code == 404
    assert db_client.post(url, content=AUDIO, headers={"Content-Type": "audio/webm"}).status_code == 401
    assert fake.calls == []


# ------------------------------------------------------------- ask the robot
class FakeAi:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def generate_json(self, system: str, prompt: str) -> Any:
        self.prompts.append(prompt)
        return self.replies.pop(0)


@pytest.mark.integration
@requires_db
def test_ask_by_voice_and_text(db_client, teacher):
    h = teacher["headers"]
    db_client.patch("/api/v1/me/settings", headers=h, json={"robot_name": "نجمة"})
    url = _slide(db_client, h, Q)  # .../slides/{sid}/listen
    base, sid = url.split("/slides/")[0], url.split("/slides/")[1].split("/")[0]
    ai = FakeAi({"answer": "البطة تقول كواك كواك!"}, {"answer": "أنا روبوت، وعمري صغير مثلكم!"})
    db_client.app.state.ai_client = ai
    db_client.app.state.transcriber = FakeTranscriber("وش تقول البطة؟")

    r = db_client.post(f"{base}/ask?slide_id={sid}", headers={**h, "Content-Type": "audio/webm"}, content=AUDIO)
    assert r.status_code == 200, r.text
    assert r.json() == {"heard": "وش تقول البطة؟", "answer": "البطة تقول كواك كواك!"}
    assert "<<<نجمة>>>" in ai.prompts[0] and "وش تقول البطة؟" in ai.prompts[0] and "سؤال للأطفال" in ai.prompts[0]

    r = db_client.post(f"{base}/ask", headers=h, json={"question": "كم عمرك؟"})
    assert r.status_code == 200 and r.json()["answer"].startswith("أنا روبوت")
    assert "الشريحة المعروضة" not in ai.prompts[1]


@pytest.mark.integration
@requires_db
def test_ask_silence_and_errors(db_client, teacher, make_teacher, make_token):
    h = teacher["headers"]
    url = _slide(db_client, h, None)
    base = url.split("/slides/")[0]
    ai = FakeAi({"oops": 1}, {"answer": ""})
    db_client.app.state.ai_client = ai
    db_client.app.state.transcriber = FakeTranscriber("")
    r = db_client.post(f"{base}/ask", headers={**h, "Content-Type": "audio/webm"}, content=AUDIO)
    assert r.json() == {"heard": "", "answer": None} and ai.prompts == []  # nothing heard -> no AI call
    assert db_client.post(f"{base}/ask", headers=h, json={"question": ""}).status_code == 422
    assert db_client.post(f"{base}/ask", headers=h, json={"question": "سؤال"}).status_code == 502
    o = {"Authorization": f"Bearer {make_token(make_teacher('أ. هند'))}"}
    assert db_client.post(f"{base}/ask", headers=o, json={"question": "سؤال"}).status_code == 404
    from uuid import uuid4
    assert db_client.post(f"{base}/ask?slide_id={uuid4()}", headers=h, json={"question": "سؤال"}).status_code == 404
