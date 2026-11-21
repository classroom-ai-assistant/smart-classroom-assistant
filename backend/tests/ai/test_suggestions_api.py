"""AI suggestions against a real Postgres with the real migrations and RLS.
The AI itself is a fake: tests never call Gemini.
Skipped unless TEST_ADMIN_DATABASE_URL points at a local Postgres.
"""

from typing import Any
from uuid import uuid4

import pytest

from app.modules.ai.deps import AiRateLimiter
from tests.db.fixtures import requires_db

pytestmark = [pytest.mark.integration, requires_db]

STORY = {"title": "الفراشة", "content": {"segments": [{"text": "طارت الفراشة", "question": "وين طارت؟"}]}}
QA = {"title": "أسئلة", "content": {"questions": [{"question": "وش لون الفراشة؟", "expected_answers": ["ملونة"]}]}}
GAME = {"title": "لعبة", "content": {"instructions": "نطير مثل الفراشة", "steps": [{"text": "افتحوا أيديكم"}]}}


class FakeAi:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    async def generate_json(self, system: str, prompt: str) -> Any:
        self.prompts.append((system, prompt))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def ai(db_client):
    fake = FakeAi()
    db_client.app.state.ai_client = fake
    return fake


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. هند")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


def _lesson(client, headers, age="age_3_4"):
    r = client.post("/api/v1/lessons", headers=headers, json={"title": "الفراشات", "topic": "دورة حياة الفراشة", "age_group": age})
    assert r.status_code == 201, r.text
    return r.json()


def _url(lesson, tail=""):
    return f"/api/v1/lessons/{lesson['id']}/suggestions{tail}"


def test_suggestion_is_proposed_and_does_not_change_the_lesson(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai.replies = [{"title": " الفراشة ", "content": {"segments": [{"text": "طارت", "question": "وين؟", "extra": 1}]}} , STORY]

    r = db_client.post(_url(lesson), headers=h, json={"type": "story", "notes": "قصة قصيرة"})
    assert r.status_code == 201, r.text
    s = r.json()
    assert (s["approval_status"], s["origin"], s["order_index"], s["type"]) == ("proposed", "ai", None, "story")
    # the first reply had an unknown field, so the service asked again
    assert len(ai.prompts) == 2 and "ردّك السابق" in ai.prompts[1][1]

    got = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()
    assert got["status"] == "draft" and got["activities"] == []
    assert [x["id"] for x in got["suggestions"]] == [s["id"]]
    assert db_client.get("/api/v1/lessons", headers=h).json()["items"][0]["activity_count"] == 0


def test_prompt_carries_lesson_and_age_but_nothing_else(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h, age="age_5_6")
    ai.replies = [GAME]
    db_client.post(_url(lesson), headers=h, json={"type": "interactive"})
    system, prompt = ai.prompts[0]
    assert "5 إلى 6 سنوات" in system
    assert "الفراشات" in prompt and "دورة حياة الفراشة" in prompt
    assert str(teacher["id"]) not in system + prompt


def test_approve_places_it_last_and_makes_the_lesson_ready(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    manual = db_client.post(f"/api/v1/lessons/{lesson['id']}/activities", headers=h, json={"type": "qa_dialogue", **QA}).json()
    ai.replies = [STORY]
    s = db_client.post(_url(lesson), headers=h, json={"type": "story"}).json()

    r = db_client.post(_url(lesson, f"/{s['id']}/approve"), headers=h, json={"title": "فراشتي"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert (a["approval_status"], a["origin"], a["order_index"], a["title"]) == ("approved", "ai", 1, "فراشتي")

    got = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()
    assert [x["id"] for x in got["activities"]] == [manual["id"], s["id"]]
    assert got["suggestions"] == [] and got["status"] == "ready"
    # an approved suggestion is no longer a suggestion
    assert db_client.post(_url(lesson, f"/{s['id']}/approve"), headers=h).status_code == 404


def test_approve_with_edited_content_is_validated_against_its_type(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai.replies = [QA]
    s = db_client.post(_url(lesson), headers=h, json={"type": "qa_dialogue"}).json()
    bad = db_client.post(_url(lesson, f"/{s['id']}/approve"), headers=h, json={"content": {"segments": [{"text": "x"}]}})
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"].startswith("content")
    good = db_client.post(
        _url(lesson, f"/{s['id']}/approve"), headers=h, json={"content": {"questions": [{"question": "وش تاكل الفراشة؟"}]}}
    )
    assert good.status_code == 200 and good.json()["content"]["questions"][0]["question"] == "وش تاكل الفراشة؟"


def test_reject_deletes_the_suggestion(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai.replies = [GAME]
    s = db_client.post(_url(lesson), headers=h, json={"type": "interactive"}).json()
    assert db_client.delete(_url(lesson, f"/{s['id']}"), headers=h).status_code == 204
    assert db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()["suggestions"] == []
    assert db_client.delete(_url(lesson, f"/{s['id']}"), headers=h).status_code == 404


def test_placed_activities_cannot_be_approved_or_rejected_as_suggestions(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    manual = db_client.post(f"/api/v1/lessons/{lesson['id']}/activities", headers=h, json={"type": "story", **STORY}).json()
    assert db_client.delete(_url(lesson, f"/{manual['id']}"), headers=h).status_code == 404
    assert db_client.post(_url(lesson, f"/{manual['id']}/approve"), headers=h).status_code == 404


def test_full_lesson_creates_three_proposed_activities(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai.replies = [
        {"activities": [{"type": "interactive", **GAME}, {"type": "story", **STORY}, {"type": "qa_dialogue", **QA}]}
    ]
    r = db_client.post(_url(lesson, "/lesson"), headers=h, json={})
    assert r.status_code == 201, r.text
    assert [x["type"] for x in r.json()] == ["story", "qa_dialogue", "interactive"]
    assert all(x["approval_status"] == "proposed" for x in r.json())


def test_full_lesson_missing_a_type_fails_after_one_retry(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    partial = {"activities": [{"type": "story", **STORY}]}
    ai.replies = [partial, partial]
    r = db_client.post(_url(lesson, "/lesson"), headers=h, json={})
    assert r.status_code == 502 and r.json()["error"]["code"] == "ai_failed"
    assert db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()["suggestions"] == []


def test_improve_returns_a_draft_without_saving(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai.replies = [STORY]
    r = db_client.post(_url(lesson, "/improve"), headers=h, json={"type": "story", "text": "كان فيه فراشه حلوه طارت"})
    assert r.status_code == 200, r.text
    assert r.json() == {"type": "story", **STORY}
    assert "كان فيه فراشه حلوه طارت" in ai.prompts[0][1]
    got = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()
    assert got["activities"] == [] and got["suggestions"] == []


def test_pending_suggestions_are_capped(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai.replies = [GAME] * 20
    for _ in range(20):
        assert db_client.post(_url(lesson), headers=h, json={"type": "interactive"}).status_code == 201
    r = db_client.post(_url(lesson), headers=h, json={"type": "interactive"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == "too_many"
    assert ai.replies == []  # the AI was not called for the refused request


def test_rate_limit_per_teacher(db_client, teacher, ai):
    h = teacher["headers"]
    db_client.app.state.ai_limiter = AiRateLimiter(limit=1)
    lesson = _lesson(db_client, h)
    ai.replies = [GAME]
    assert db_client.post(_url(lesson), headers=h, json={"type": "interactive"}).status_code == 201
    r = db_client.post(_url(lesson), headers=h, json={"type": "interactive"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "ai_rate_limited"


def test_without_ai_key_generation_is_503_but_review_still_works(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai.replies = [GAME]
    s = db_client.post(_url(lesson), headers=h, json={"type": "interactive"}).json()
    db_client.app.state.ai_client = None
    r = db_client.post(_url(lesson), headers=h, json={"type": "story"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"
    assert db_client.post(_url(lesson, f"/{s['id']}/approve"), headers=h).status_code == 200


def test_invalid_requests(db_client, teacher, ai):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    for body in [{"type": "song"}, {"type": "story", "notes": "x" * 501}, {"type": "story", "child_name": "سارة"}]:
        assert db_client.post(_url(lesson), headers=h, json=body).status_code == 422
    assert db_client.post(_url(lesson, "/improve"), headers=h, json={"type": "story", "text": "  "}).status_code == 422
    assert ai.prompts == []


def test_another_teacher_cannot_use_or_see_suggestions(db_client, teacher, ai, make_teacher, make_token):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai.replies = [STORY]
    s = db_client.post(_url(lesson), headers=h, json={"type": "story"}).json()
    other_id = make_teacher("أ. ريم")
    o = {"Authorization": f"Bearer {make_token(other_id)}"}
    assert db_client.post(_url(lesson), headers=o, json={"type": "story"}).status_code == 404
    assert db_client.post(_url(lesson, "/improve"), headers=o, json={"type": "story", "text": "x"}).status_code == 404
    assert db_client.post(_url(lesson, f"/{s['id']}/approve"), headers=o).status_code == 404
    assert db_client.delete(_url(lesson, f"/{s['id']}"), headers=o).status_code == 404
    assert ai.prompts and len(ai.prompts) == 1  # only the owner's request reached the AI
    assert db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()["suggestions"][0]["id"] == s["id"]


def test_unknown_lesson_is_404(db_client, teacher, ai):
    r = db_client.post(f"/api/v1/lessons/{uuid4()}/suggestions", headers=teacher["headers"], json={"type": "story"})
    assert r.status_code == 404
