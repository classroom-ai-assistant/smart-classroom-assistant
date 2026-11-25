"""Slides (the lesson as a deck) against a real Postgres with the real
migrations and RLS. Local Postgres only."""

import asyncio
import json
from uuid import uuid4

import asyncpg
import pytest

from tests.db.fixtures import requires_db

pytestmark = [pytest.mark.integration, requires_db]

TITLE = {"id": "t", "type": "text", "text": "الرقم ثلاثة", "x": 10, "y": 10, "w": 80, "h": 20}


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. لمى")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


@pytest.fixture
def upload(migrated_dsn, db_client):
    def _upload(t, mime="image/png", ext="png"):
        path = f"{t['id']}/{uuid4()}.{ext}"

        async def insert():
            conn = await asyncpg.connect(migrated_dsn)
            try:
                await conn.execute(
                    "insert into storage.objects (bucket_id, name, metadata) values ('teacher-assets', $1, $2::jsonb)",
                    path,
                    json.dumps({"size": 1000, "mimetype": mime}),
                )
            finally:
                await conn.close()

        asyncio.run(insert())
        r = db_client.post("/api/v1/assets", headers=t["headers"], json={"storage_path": path, "file_name": f"f.{ext}"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return _upload


def _lesson(client, h):
    return client.post(
        "/api/v1/lessons", headers=h, json={"title": "الأرقام", "topic": "العد", "age_group": "age_4_5"}
    ).json()


def _url(lesson, tail=""):
    return f"/api/v1/lessons/{lesson['id']}/slides{tail}"


def _add(client, h, lesson, **body):
    r = client.post(_url(lesson), headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_new_lesson_has_no_slides_and_is_draft(db_client, teacher):
    lesson = _lesson(db_client, teacher["headers"])
    assert lesson["slides"] == [] and lesson["slide_count"] == 0 and lesson["status"] == "draft"


def test_blank_slide_then_lesson_is_ready(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    s = _add(db_client, h, lesson)
    assert s["order_index"] == 0 and s["layout"] == {"background": "#FAEFE9", "elements": [], "transition": "none"}
    assert s["speech"] is None and s["question"] is None
    got = db_client.get(f"/api/v1/lessons/{lesson['id']}", headers=h).json()
    assert got["status"] == "ready" and got["slide_count"] == 1 and [x["id"] for x in got["slides"]] == [s["id"]]


def test_full_slide_with_image_video_speech_and_question(db_client, teacher, upload):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    img, vid = upload(teacher), upload(teacher, "video/mp4", "mp4")
    layout = {
        "background": "#CFD6E8",
        "elements": [
            TITLE,
            {"id": "i", "type": "image", "asset_id": img, "x": 5, "y": 35, "w": 40, "h": 50},
            {"id": "v", "type": "video", "asset_id": vid, "x": 55, "y": 35, "w": 40, "h": 50, "muted": True},
        ],
    }
    s = _add(
        db_client,
        h,
        lesson,
        layout=layout,
        speech="عندي ثلاث تفاحات، عدّوا معي",
        question={"question": "كم تفاحة؟", "expected_answers": ["ثلاث"]},
    )
    assert [e["type"] for e in s["layout"]["elements"]] == ["text", "image", "video"]
    assert s["question"] == {"question": "كم تفاحة؟", "expected_answers": ["ثلاث"]}


def test_insert_in_middle_duplicate_reorder_delete_keep_positions(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    a, b = _add(db_client, h, lesson, speech="أ"), _add(db_client, h, lesson, speech="ب")
    mid = _add(db_client, h, lesson, speech="وسط", position=1)
    order = lambda: [(x["speech"], x["order_index"]) for x in db_client.get(_url(lesson), headers=h).json()]  # noqa: E731
    assert order() == [("أ", 0), ("وسط", 1), ("ب", 2)]

    dup = db_client.post(_url(lesson, f"/{a['id']}/duplicate"), headers=h)
    assert dup.status_code == 201
    assert order() == [("أ", 0), ("أ", 1), ("وسط", 2), ("ب", 3)]

    ids = [x["id"] for x in db_client.get(_url(lesson), headers=h).json()]
    r = db_client.put(_url(lesson, "/order"), headers=h, json={"slide_ids": ids[::-1]})
    assert r.status_code == 200 and [x["speech"] for x in r.json()] == ["ب", "وسط", "أ", "أ"]

    assert db_client.delete(_url(lesson, f"/{mid['id']}"), headers=h).status_code == 204
    assert order() == [("ب", 0), ("أ", 1), ("أ", 2)]
    assert b["id"] in {x["id"] for x in db_client.get(_url(lesson), headers=h).json()}


@pytest.mark.parametrize("mode", ["missing", "duplicate", "foreign"])
def test_reorder_must_match(db_client, teacher, mode):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ids = [_add(db_client, h, lesson)["id"] for _ in range(2)]
    bad = {"missing": ids[:1], "duplicate": [ids[0], ids[0]], "foreign": [ids[0], str(uuid4())]}[mode]
    assert db_client.put(_url(lesson, "/order"), headers=h, json={"slide_ids": bad}).status_code == 422


def test_update_partial_and_clear(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    s = _add(db_client, h, lesson, speech="مرحبا", question={"question": "كيفكم؟"})
    url = _url(lesson, f"/{s['id']}")
    r = db_client.patch(url, headers=h, json={"layout": {"background": "#FCDC9F", "elements": [TITLE]}})
    assert r.status_code == 200 and r.json()["speech"] == "مرحبا" and r.json()["layout"]["background"] == "#FCDC9F"
    r = db_client.patch(url, headers=h, json={"speech": None, "question": None})
    assert r.json()["speech"] is None and r.json()["question"] is None
    assert db_client.patch(url, headers=h, json={}).status_code == 422
    assert db_client.patch(url, headers=h, json={"layout": None}).status_code == 422


def test_files_must_be_hers_and_the_right_kind(db_client, teacher, upload, make_teacher, make_token):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    img = upload(teacher)
    other = {"id": make_teacher("أ. سارة")}
    other["headers"] = {"Authorization": f"Bearer {make_token(other['id'])}"}
    cases = [
        {"id": "x", "type": "video", "asset_id": img, "x": 0, "y": 0, "w": 10, "h": 10},  # image used as video
        {"id": "x", "type": "image", "asset_id": upload(other), "x": 0, "y": 0, "w": 10, "h": 10},  # not hers
        {"id": "x", "type": "image", "asset_id": str(uuid4()), "x": 0, "y": 0, "w": 10, "h": 10},  # no such file
    ]
    for el in cases:
        r = db_client.post(_url(lesson), headers=h, json={"layout": {"elements": [el]}})
        assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == "unknown_asset"


@pytest.mark.parametrize(
    "body",
    [
        {"layout": {"elements": [{"id": "a", "type": "gif", "x": 0, "y": 0, "w": 1, "h": 1}]}},
        {"speech": "x" * 2001},
        {"question": {"question": ""}},
        {"question": {"question": "؟", "layouts": {}}},
        {"position": -1},
        {"child_name": "سارة"},
    ],
)
def test_invalid_slides(db_client, teacher, body):
    lesson = _lesson(db_client, teacher["headers"])
    assert db_client.post(_url(lesson), headers=teacher["headers"], json=body).status_code == 422


def test_copy_lesson_copies_slides(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    _add(db_client, h, lesson, speech="١")
    _add(db_client, h, lesson, speech="٢")
    copy = db_client.post(f"/api/v1/lessons/{lesson['id']}/copy", headers=h).json()
    assert [s["speech"] for s in copy["slides"]] == ["١", "٢"]
    db_client.delete(_url(copy, f"/{copy['slides'][0]['id']}"), headers=h)
    assert len(db_client.get(_url(lesson), headers=h).json()) == 2


def test_another_teacher_cannot_touch_slides(db_client, teacher, make_teacher, make_token):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    s = _add(db_client, h, lesson, speech="سري")
    o = {"Authorization": f"Bearer {make_token(make_teacher('أ. منى'))}"}
    assert db_client.get(_url(lesson), headers=o).status_code == 404
    assert db_client.post(_url(lesson), headers=o, json={}).status_code == 404
    assert db_client.patch(_url(lesson, f"/{s['id']}"), headers=o, json={"speech": "x"}).status_code == 404
    assert db_client.post(_url(lesson, f"/{s['id']}/duplicate"), headers=o).status_code == 404
    assert db_client.delete(_url(lesson, f"/{s['id']}"), headers=o).status_code == 404
    assert db_client.put(_url(lesson, "/order"), headers=o, json={"slide_ids": [s["id"]]}).status_code == 404
    assert db_client.get(_url(lesson), headers=h).json()[0]["speech"] == "سري"


def test_deleting_lesson_deletes_slides(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    _add(db_client, h, lesson)
    assert db_client.delete(f"/api/v1/lessons/{lesson['id']}", headers=h).status_code == 204
    assert db_client.get(_url(lesson), headers=h).status_code == 404


# ------------------------------------------------------- editor polish (step 1)
def test_new_shapes_fonts_crop_and_background_image(db_client, teacher, upload):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    img = upload(teacher)
    layout = {
        "background": "#FAEFE9",
        "background_asset_id": img,
        "elements": [
            {"id": "t", "type": "text", "text": "ب", "font": "lalezar", "underline": True, "background": "#FCDC9F",
             "x": 0, "y": 0, "w": 30, "h": 30, "opacity": 0.8, "locked": True},
            *[{"id": f"s{i}", "type": "shape", "shape": s, "x": 0, "y": 0, "w": 5, "h": 5}
              for i, s in enumerate(["triangle", "diamond", "hexagon", "arrow", "speech_bubble", "sun", "moon", "flower", "line"])],
            {"id": "i", "type": "image", "asset_id": img, "x": 50, "y": 0, "w": 40, "h": 40,
             "crop": {"x": 10, "y": 10, "w": 50, "h": 60}, "flip": True},
        ],
    }
    s = _add(db_client, h, lesson, layout=layout)
    assert s["layout"]["background_asset_id"] == img
    assert s["layout"]["elements"][0]["font"] == "lalezar" and s["layout"]["elements"][-1]["crop"]["w"] == 50


@pytest.mark.parametrize(
    "layout",
    [
        {"background_asset_id": str(uuid4()), "elements": []},  # background image not hers
        {"elements": [{"id": "t", "type": "text", "text": "x", "font": "comic_sans", "x": 0, "y": 0, "w": 1, "h": 1}]},
        {"elements": [{"id": "s", "type": "shape", "shape": "dragon", "x": 0, "y": 0, "w": 1, "h": 1}]},
        {"elements": [{"id": "s", "type": "shape", "shape": "star", "opacity": 2, "x": 0, "y": 0, "w": 1, "h": 1}]},
    ],
)
def test_editor_polish_rejects(db_client, teacher, layout):
    lesson = _lesson(db_client, teacher["headers"])
    assert db_client.post(_url(lesson), headers=teacher["headers"], json={"layout": layout}).status_code == 422


def test_crop_must_stay_inside(db_client, teacher, upload):
    lesson = _lesson(db_client, teacher["headers"])
    img = upload(teacher)
    el = {"id": "i", "type": "image", "asset_id": img, "x": 0, "y": 0, "w": 10, "h": 10, "crop": {"x": 60, "y": 0, "w": 50, "h": 50}}
    assert db_client.post(_url(lesson), headers=teacher["headers"], json={"layout": {"elements": [el]}}).status_code == 422
