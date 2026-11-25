"""مكتبتي for slides against a real Postgres with the real migrations and RLS."""

import asyncio
import json
from uuid import uuid4

import asyncpg
import pytest

from tests.db.fixtures import requires_db

pytestmark = [pytest.mark.integration, requires_db]

STAR = {"id": "s", "type": "shape", "shape": "star", "x": 10, "y": 10, "w": 20, "h": 20}


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. لمى")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


def _lesson(client, h):
    return client.post("/api/v1/lessons", headers=h, json={"title": "درس", "topic": "موضوع", "age_group": "age_4_5"}).json()


def _slide(client, h, lesson, **body):
    r = client.post(f"/api/v1/lessons/{lesson['id']}/slides", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_save_list_insert_rename_delete(db_client, teacher):
    h = teacher["headers"]
    a = _lesson(db_client, h)
    s = _slide(db_client, h, a, layout={"background": "#FCDC9F", "elements": [STAR]}, speech="نجمة", question={"question": "كم رأس؟"})
    r = db_client.post(f"/api/v1/lessons/{a['id']}/slides/{s['id']}/save", headers=h, json={"title": "نجمتي"})
    assert r.status_code == 201, r.text
    saved = r.json()
    assert saved["title"] == "نجمتي" and saved["speech"] == "نجمة" and saved["layout"]["elements"][0]["shape"] == "star"

    listing = db_client.get("/api/v1/saved-slides", headers=h).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == saved["id"]

    b = _lesson(db_client, h)
    _slide(db_client, h, b, speech="أول")
    ins = db_client.post(f"/api/v1/lessons/{b['id']}/slides/from-library", headers=h, json={"saved_slide_id": saved["id"], "position": 0})
    assert ins.status_code == 201, ins.text
    deck = db_client.get(f"/api/v1/lessons/{b['id']}/slides", headers=h).json()
    assert [x["speech"] for x in deck] == ["نجمة", "أول"] and deck[0]["question"] == {"question": "كم رأس؟", "expected_answers": []}

    # editing the inserted slide does not change the library copy
    db_client.patch(f"/api/v1/lessons/{b['id']}/slides/{deck[0]['id']}", headers=h, json={"speech": "تغيّرت"})
    assert db_client.get(f"/api/v1/saved-slides/{saved['id']}", headers=h).json()["speech"] == "نجمة"

    assert db_client.patch(f"/api/v1/saved-slides/{saved['id']}", headers=h, json={"title": "نجمة ذهبية"}).json()["title"] == "نجمة ذهبية"
    assert db_client.delete(f"/api/v1/saved-slides/{saved['id']}", headers=h).status_code == 204
    assert db_client.get(f"/api/v1/saved-slides/{saved['id']}", headers=h).status_code == 404


def test_insert_fails_if_image_was_deleted(db_client, teacher, migrated_dsn):
    h = teacher["headers"]
    path = f"{teacher['id']}/{uuid4()}.png"

    async def upload():
        conn = await asyncpg.connect(migrated_dsn)
        try:
            await conn.execute(
                "insert into storage.objects (bucket_id, name, metadata) values ('teacher-assets', $1, $2::jsonb)",
                path, json.dumps({"size": 100, "mimetype": "image/png"}),
            )
        finally:
            await conn.close()

    asyncio.run(upload())
    img = db_client.post("/api/v1/assets", headers=h, json={"storage_path": path, "file_name": "a.png"}).json()["id"]
    a = _lesson(db_client, h)
    s = _slide(db_client, h, a, layout={"elements": [{"id": "i", "type": "image", "asset_id": img, "x": 0, "y": 0, "w": 10, "h": 10}]})
    saved = db_client.post(f"/api/v1/lessons/{a['id']}/slides/{s['id']}/save", headers=h, json={"title": "صورة"}).json()
    db_client.delete(f"/api/v1/assets/{img}", headers=h)
    r = db_client.post(f"/api/v1/lessons/{a['id']}/slides/from-library", headers=h, json={"saved_slide_id": saved["id"]})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == "unknown_asset"


def test_library_is_private(db_client, teacher, make_teacher, make_token):
    h = teacher["headers"]
    a = _lesson(db_client, h)
    s = _slide(db_client, h, a, speech="سري")
    saved = db_client.post(f"/api/v1/lessons/{a['id']}/slides/{s['id']}/save", headers=h, json={"title": "سري"}).json()
    o = {"Authorization": f"Bearer {make_token(make_teacher('أ. هند'))}"}
    other_lesson = _lesson(db_client, o)
    assert db_client.get("/api/v1/saved-slides", headers=o).json()["total"] == 0
    assert db_client.get(f"/api/v1/saved-slides/{saved['id']}", headers=o).status_code == 404
    assert db_client.patch(f"/api/v1/saved-slides/{saved['id']}", headers=o, json={"title": "x"}).status_code == 404
    assert db_client.delete(f"/api/v1/saved-slides/{saved['id']}", headers=o).status_code == 404
    # cannot save someone else's slide, nor insert someone else's saved slide
    assert db_client.post(f"/api/v1/lessons/{a['id']}/slides/{s['id']}/save", headers=o, json={"title": "x"}).status_code == 404
    r = db_client.post(f"/api/v1/lessons/{other_lesson['id']}/slides/from-library", headers=o, json={"saved_slide_id": saved["id"]})
    assert r.status_code == 404


@pytest.mark.parametrize("body", [{"title": ""}, {"title": "x" * 151}, {"title": "x", "layout": {}}])
def test_invalid_save(db_client, teacher, body):
    h = teacher["headers"]
    a = _lesson(db_client, h)
    s = _slide(db_client, h, a)
    assert db_client.post(f"/api/v1/lessons/{a['id']}/slides/{s['id']}/save", headers=h, json=body).status_code == 422
