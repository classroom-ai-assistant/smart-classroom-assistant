"""Robot persona settings and automatic narration. AI is faked; database
tests use the local Postgres (role authenticated + RLS, as in production)."""

from typing import Any

import pytest

from app.modules.slides.narration import describe_slide, narrate_prompt, pick_speeches
from tests.db.fixtures import requires_db


# ------------------------------------------------------------- settings (fake repo)
def test_robot_defaults_and_update(client, auth_headers):
    s = client.get("/api/v1/me", headers=auth_headers).json()["settings"]
    assert (s["robot_name"], s["robot_style"], s["robot_voice"]) == ("روبو", "playful", "Puck")
    r = client.patch(
        "/api/v1/me/settings",
        headers=auth_headers,
        json={"robot_name": "  نجمة  ", "robot_style": "storyteller", "robot_voice": "Kore"},
    )
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert (s["robot_name"], s["robot_style"], s["robot_voice"]) == ("نجمة", "storyteller", "Kore")


@pytest.mark.parametrize(
    "payload",
    [
        {"robot_name": ""},
        {"robot_name": "   "},
        {"robot_name": "x" * 31},
        {"robot_name": "<script>"},
        {"robot_name": "روبو https://x.y"},
        {"robot_name": None},
        {"robot_style": "angry"},
        {"robot_voice": "Darth"},
    ],
)
def test_bad_robot_settings_are_rejected(client, auth_headers, payload):
    assert client.patch("/api/v1/me/settings", headers=auth_headers, json=payload).status_code == 422


# ------------------------------------------------------------- pure helpers
SLIDES = [
    {"layout": {"elements": [{"type": "text", "text": "الرقم ثلاثة"}, {"type": "sticker", "name": "red_apple"}]},
     "speech": None, "speech_auto": False, "question": None},
    {"layout": {"elements": [{"type": "placeholder", "query": "ثلاث بطات"}, {"type": "text", "binding": "question"}]},
     "speech": "كلام كتبته المعلمة", "speech_auto": False, "question": {"question": "كم بطة؟"}},
    {"layout": {"elements": [{"type": "shape", "shape": "star"}]}, "speech": None, "speech_auto": False, "question": None},
]


def test_describe_slide_lists_what_children_see():
    labels = {"red_apple": "تفاحة حمراء"}
    assert describe_slide(SLIDES[0], labels) == "نص: الرقم ثلاثة، صورة: تفاحة حمراء"
    assert "صورة: ثلاث بطات" in describe_slide(SLIDES[1], labels) and "سؤال للأطفال: كم بطة؟" in describe_slide(SLIDES[1], labels)
    assert describe_slide(SLIDES[2], labels) == "(شريحة بلا نص)"


def test_prompt_has_persona_and_keeps_teacher_words_as_context():
    p = narrate_prompt({"title": "رقم ٣", "topic": "الأرقام"}, "نجمة", "calm", SLIDES, {0, 2})
    assert "<<<نجمة>>>" in p and "هادئ" in p
    assert "اكتب كلامك أنت للشرائح رقم: 1, 3" in p
    assert "كلام كتبته المعلمة" in p  # context for slide 2, not to be rewritten


def test_pick_speeches_keeps_only_wanted_slides():
    raw = {"slides": [{"n": 1, "speech": " مرحبا "}, {"n": 2, "speech": "لا"}, {"n": "x"}, {"n": 3, "speech": ""},
                      {"n": 1, "speech": "مكرر"}, "junk", {"n": 3, "speech": "ي" * 3000}]}
    found = pick_speeches(raw, {0, 2})
    assert found[0] == "مرحبا" and 1 not in found and len(found[2]) == 2000
    assert pick_speeches("nonsense", {0}) == {}


# ------------------------------------------------------------- API (real DB)
class FakeAi:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    async def generate_json(self, system: str, prompt: str) -> Any:
        self.prompts.append((system, prompt))
        return self.replies.pop(0)


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. لمى")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


def _deck(client, h, speeches):
    lesson = client.post("/api/v1/lessons", headers=h,
                         json={"title": "الرقم ثلاثة", "topic": "الأرقام", "age_group": "age_4_5"}).json()
    for i, sp in enumerate(speeches):
        body = {"layout": {"elements": [{"id": "t", "type": "text", "text": f"شريحة {i}", "x": 1, "y": 1, "w": 50, "h": 20}]}}
        if sp:
            body["speech"] = sp
        assert client.post(f"/api/v1/lessons/{lesson['id']}/slides", headers=h, json=body).status_code == 201
    return lesson


@pytest.mark.integration
@requires_db
def test_robot_settings_saved_under_rls(db_client, teacher):
    h = teacher["headers"]
    r = db_client.patch("/api/v1/me/settings", headers=h, json={"robot_name": "نجمة", "robot_style": "calm"})
    assert r.status_code == 200, r.text
    s = db_client.get("/api/v1/me", headers=h).json()["settings"]
    assert s["robot_name"] == "نجمة" and s["robot_style"] == "calm" and s["robot_voice"] == "Puck"


@pytest.mark.integration
@requires_db
def test_narrate_writes_auto_words_and_keeps_teacher_words(db_client, teacher):
    h = teacher["headers"]
    db_client.patch("/api/v1/me/settings", headers=h, json={"robot_name": "نجمة", "robot_style": "storyteller"})
    lesson = _deck(db_client, h, [None, "كلامي أنا", None])
    url = f"/api/v1/lessons/{lesson['id']}/narrate"
    ai = FakeAi(
        {"slides": [{"n": 1, "speech": "مرحباً يا أصدقائي، أنا نجمة!"}, {"n": 2, "speech": "يجب ألا يُحفظ"},
                    {"n": 3, "speech": "أحسنتم يا أبطال"}]},
        {"slides": [{"n": 1, "speech": "نسخة ثانية"}, {"n": 3, "speech": "ختام جديد"}]},
        {"slides": [{"n": 2, "speech": "الكل من جديد"}]},
    )
    db_client.app.state.ai_client = ai

    r = db_client.post(url, headers=h, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written"] == 2 and body["kept"] == 1
    assert [(s["speech"], s["speech_auto"]) for s in body["slides"]] == [
        ("مرحباً يا أصدقائي، أنا نجمة!", True), ("كلامي أنا", False), ("أحسنتم يا أبطال", True)]
    system, prompt = ai.prompts[0]
    assert "<<<نجمة>>>" in prompt and "حكواتي" in prompt and str(teacher["id"]) not in system + prompt

    # robot words get rewritten next time; teacher words stay
    body = db_client.post(url, headers=h).json()
    assert [s["speech"] for s in body["slides"]] == ["نسخة ثانية", "كلامي أنا", "ختام جديد"]

    # the teacher edits slide 1 -> it becomes hers
    sid = body["slides"][0]["id"]
    e = db_client.patch(f"/api/v1/lessons/{lesson['id']}/slides/{sid}", headers=h, json={"speech": "عدّلته"})
    assert e.json()["speech_auto"] is False

    # rewrite_all asks the robot for every slide, including hers
    body = db_client.post(url, headers=h, json={"rewrite_all": True}).json()
    assert body["written"] == 1 and body["slides"][1]["speech"] == "الكل من جديد" and body["slides"][1]["speech_auto"]
    assert "اكتب كلامك أنت للشرائح رقم: 1, 2, 3" in ai.prompts[2][1]


@pytest.mark.integration
@requires_db
def test_narrate_skips_ai_when_all_words_are_the_teachers(db_client, teacher):
    h = teacher["headers"]
    lesson = _deck(db_client, h, ["أ", "ب"])
    ai = FakeAi()
    db_client.app.state.ai_client = ai
    r = db_client.post(f"/api/v1/lessons/{lesson['id']}/narrate", headers=h)
    assert r.status_code == 200 and r.json()["written"] == 0 and r.json()["kept"] == 2 and ai.prompts == []


@pytest.mark.integration
@requires_db
def test_narrate_errors(db_client, teacher, make_teacher, make_token):
    h = teacher["headers"]
    empty = _deck(db_client, h, [])
    db_client.app.state.ai_client = FakeAi()
    r = db_client.post(f"/api/v1/lessons/{empty['id']}/narrate", headers=h)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == "empty"

    lesson = _deck(db_client, h, [None])
    o = {"Authorization": f"Bearer {make_token(make_teacher('أ. هند'))}"}
    assert db_client.post(f"/api/v1/lessons/{lesson['id']}/narrate", headers=o).status_code == 404

    db_client.app.state.ai_client = FakeAi({"slides": []}, {"oops": 1})
    r = db_client.post(f"/api/v1/lessons/{lesson['id']}/narrate", headers=h)
    assert r.status_code == 502 and r.json()["error"]["code"] == "ai_failed"
    assert db_client.get(f"/api/v1/lessons/{lesson['id']}/slides", headers=h).json()[0]["speech"] is None
