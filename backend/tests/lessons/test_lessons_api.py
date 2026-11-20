"""Lessons and activities against a real Postgres with the real migrations
and RLS (FR-005 to FR-015, BRL-03, BRL-12, ACC-03, ACC-04, ACC-12).

Skipped unless TEST_ADMIN_DATABASE_URL points at a local Postgres.
"""

from uuid import uuid4

import pytest

from tests.db.fixtures import requires_db

pytestmark = [pytest.mark.integration, requires_db]

STORY = {
    "type": "story",
    "title": "الفراشة الملونة",
    "content": {"segments": [{"text": "كان يا ما كان"}, {"text": "طارت", "question": "وين طارت؟"}]},
}
QA = {"type": "qa_dialogue", "title": "أسئلة الألوان", "content": {"questions": [{"question": "وش لون الموز؟"}]}}
GAME = {"type": "interactive", "title": "لعبة الألوان", "content": {"instructions": "نلعب", "steps": [{"text": "قفوا"}]}}


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. نورة")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


@pytest.fixture
def other(make_teacher, make_token):
    tid = make_teacher("أ. سارة")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


def _lesson(client, headers, title="الألوان"):
    r = client.post("/api/v1/lessons", headers=headers, json={"title": title, "topic": "الألوان الأساسية", "age_group": "age_4_5"})
    assert r.status_code == 201, r.text
    return r.json()


def _activity(client, headers, lesson_id, body):
    r = client.post(f"/api/v1/lessons/{lesson_id}/activities", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ lessons
def test_new_lesson_is_an_empty_draft(db_client, teacher):
    lesson = _lesson(db_client, teacher["headers"])
    assert lesson["status"] == "draft"
    assert lesson["activity_count"] == 0
    assert lesson["activities"] == []


def test_lesson_becomes_ready_with_an_approved_activity(db_client, teacher):
    lesson = _lesson(db_client, teacher["headers"])
    act = _activity(db_client, teacher["headers"], lesson["id"], STORY)
    assert act["approval_status"] == "approved" and act["origin"] == "manual" and act["order_index"] == 0
    got = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=teacher["headers"]).json()
    assert got["status"] == "ready"
    assert got["activities"][0]["content"]["segments"][1]["question"] == "وين طارت؟"


def test_list_search_and_pagination(db_client, teacher):
    for title in ["الألوان", "الحيوانات", "حيوانات البحر", "100%_خاص"]:
        _lesson(db_client, teacher["headers"], title)
    h = teacher["headers"]
    all_ = db_client.get("/api/v1/lessons", headers=h).json()
    assert all_["total"] == 4 and all_["items"][0]["title"] == "100%_خاص"  # newest first
    assert db_client.get("/api/v1/lessons?q=حيوانات", headers=h).json()["total"] == 2
    # LIKE wildcards in the search are literal, not patterns
    assert db_client.get("/api/v1/lessons?q=%25", headers=h).json()["total"] == 1
    page = db_client.get("/api/v1/lessons?limit=2&offset=2", headers=h).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    assert db_client.get("/api/v1/lessons?offset=50", headers=h).json() == {"items": [], "total": 4}


def test_update_lesson(db_client, teacher):
    lesson = _lesson(db_client, teacher["headers"])
    r = db_client.patch(f"/api/v1/lessons/{lesson['id']}", headers=teacher["headers"], json={"age_group": "mixed_3_6"})
    assert r.status_code == 200 and r.json()["age_group"] == "mixed_3_6" and r.json()["title"] == "الألوان"


@pytest.mark.parametrize(
    "body",
    [{}, {"title": ""}, {"title": None}, {"age_group": "age_7_8"}, {"topic": "س" * 201}, {"teacher_id": str(uuid4())}],
)
def test_invalid_lesson_update_is_422(db_client, teacher, body):
    lesson = _lesson(db_client, teacher["headers"])
    assert db_client.patch(f"/api/v1/lessons/{lesson['id']}", headers=teacher["headers"], json=body).status_code == 422


def test_delete_lesson_removes_its_activities(db_client, teacher):
    lesson = _lesson(db_client, teacher["headers"])
    _activity(db_client, teacher["headers"], lesson["id"], STORY)
    assert db_client.delete(f"/api/v1/lessons/{lesson['id']}", headers=teacher["headers"]).status_code == 204
    assert db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=teacher["headers"]).status_code == 404


def test_copy_lesson_leaves_original_untouched(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    _activity(db_client, h, lesson["id"], STORY)
    _activity(db_client, h, lesson["id"], QA)

    copy = db_client.post(f"/api/v1/lessons/{lesson['id']}/copy", headers=h).json()
    assert copy["title"] == "نسخة من الألوان"
    assert copy["copied_from_lesson_id"] == lesson["id"]
    assert [a["title"] for a in copy["activities"]] == ["الفراشة الملونة", "أسئلة الألوان"]
    assert copy["status"] == "ready"

    # editing the copy does not change the original (ACC-04)
    db_client.delete(f"/api/v1/lessons/{copy['id']}/activities/{copy['activities'][0]['id']}", headers=h)
    original = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()
    assert len(original["activities"]) == 2


# --------------------------------------------------------------- activities
def test_activities_are_appended_in_order(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    for body in (STORY, QA, GAME):
        _activity(db_client, h, lesson["id"], body)
    acts = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()["activities"]
    assert [a["type"] for a in acts] == ["story", "qa_dialogue", "interactive"]
    assert [a["order_index"] for a in acts] == [0, 1, 2]


def test_reorder_and_delete_keep_positions_contiguous(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ids = [_activity(db_client, h, lesson["id"], b)["id"] for b in (STORY, QA, GAME)]

    r = db_client.put(f"/api/v1/lessons/{lesson['id']}/activities/order", headers=h, json={"activity_ids": ids[::-1]})
    assert r.status_code == 200
    assert [a["id"] for a in r.json()] == ids[::-1]

    assert db_client.delete(f"/api/v1/lessons/{lesson['id']}/activities/{ids[1]}", headers=h).status_code == 204
    acts = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()["activities"]
    assert [a["id"] for a in acts] == [ids[2], ids[0]]
    assert [a["order_index"] for a in acts] == [0, 1]


@pytest.mark.parametrize("mode", ["missing", "duplicate", "foreign"])
def test_reorder_must_match_exactly(db_client, teacher, mode):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ids = [_activity(db_client, h, lesson["id"], b)["id"] for b in (STORY, QA)]
    bad = {"missing": ids[:1], "duplicate": [ids[0], ids[0]], "foreign": [ids[0], str(uuid4())]}[mode]
    r = db_client.put(f"/api/v1/lessons/{lesson['id']}/activities/order", headers=h, json={"activity_ids": bad})
    assert r.status_code == 422


def test_update_activity_content_is_validated_against_its_type(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    act = _activity(db_client, h, lesson["id"], QA)
    url = f"/api/v1/lessons/{lesson['id']}/activities/{act['id']}"

    bad = db_client.patch(url, headers=h, json={"content": {"segments": [{"text": "x"}]}})
    assert bad.status_code == 422
    assert bad.json()["error"]["details"][0]["field"].startswith("content")

    good = db_client.patch(
        url, headers=h, json={"content": {"questions": [{"question": "وش لون السماء؟", "hint": "فوق"}]}}
    )
    assert good.status_code == 200
    assert good.json()["content"]["questions"][0]["hint"] == "فوق"
    assert good.json()["title"] == "أسئلة الألوان"


def test_empty_activity_update_is_422(db_client, teacher):
    lesson = _lesson(db_client, teacher["headers"])
    act = _activity(db_client, teacher["headers"], lesson["id"], GAME)
    r = db_client.patch(f"/api/v1/lessons/{lesson['id']}/activities/{act['id']}", headers=teacher["headers"], json={})
    assert r.status_code == 422


# ------------------------------------------------------------- isolation
def test_teacher_cannot_see_or_touch_another_teachers_lessons(db_client, teacher, other):
    lesson = _lesson(db_client, teacher["headers"])
    act = _activity(db_client, teacher["headers"], lesson["id"], STORY)
    o = other["headers"]
    lid, aid = lesson["id"], act["id"]

    assert db_client.get("/api/v1/lessons", headers=o).json()["total"] == 0
    assert db_client.get(f"/api/v1/lessons/{lid}", headers=o).status_code == 404
    assert db_client.patch(f"/api/v1/lessons/{lid}", headers=o, json={"title": "مخترق"}).status_code == 404
    assert db_client.delete(f"/api/v1/lessons/{lid}", headers=o).status_code == 404
    assert db_client.post(f"/api/v1/lessons/{lid}/copy", headers=o).status_code == 404
    assert db_client.post(f"/api/v1/lessons/{lid}/activities", headers=o, json=STORY).status_code == 404
    assert db_client.patch(f"/api/v1/lessons/{lid}/activities/{aid}", headers=o, json={"title": "x"}).status_code == 404
    assert db_client.delete(f"/api/v1/lessons/{lid}/activities/{aid}", headers=o).status_code == 404
    assert db_client.put(f"/api/v1/lessons/{lid}/activities/order", headers=o, json={"activity_ids": [aid]}).status_code == 404

    # the owner's data is unchanged
    owner_view = db_client.get(f"/api/v1/lessons/{lid}", headers=teacher["headers"]).json()
    assert owner_view["title"] == "الألوان" and len(owner_view["activities"]) == 1


def test_404_does_not_reveal_whether_the_lesson_exists(db_client, teacher, other):
    lesson = _lesson(db_client, teacher["headers"])
    foreign = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=other["headers"]).json()
    missing = db_client.get(f"/api/v1/lessons/{uuid4()}", headers=other["headers"]).json()
    assert foreign == missing


def test_lessons_require_a_token(db_client):
    assert db_client.get("/api/v1/lessons").status_code == 401
    assert db_client.post("/api/v1/lessons", json={}).status_code == 401
