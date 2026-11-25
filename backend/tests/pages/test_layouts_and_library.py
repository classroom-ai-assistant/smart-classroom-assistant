"""Page layouts inside activities, and مكتبتي (saved pages), against a real
Postgres with the real migrations and RLS. Local Postgres only."""

import asyncio
import json
from uuid import uuid4

import asyncpg
import pytest

from app.modules.pages.layout import Layout, PageLayouts
from tests.db.fixtures import requires_db

# ------------------------------------------------------------ pure schema
SLIDE = {
    "background": "#FAEFE9",
    "elements": [
        {"id": "t1", "type": "text", "binding": "text", "x": 10, "y": 60, "w": 80, "h": 20, "font_size": 7},
        {"id": "n3", "type": "text", "text": "٣", "x": 70, "y": 10, "w": 20, "h": 40, "font_size": 30, "bold": True},
        {"id": "s1", "type": "shape", "shape": "star", "x": 5, "y": 5, "w": 10, "h": 10, "fill": "#FCDC9F"},
    ],
}


def test_layout_accepts_a_page():
    layouts = PageLayouts.model_validate({"slide": SLIDE})
    assert layouts.slide and len(layouts.slide.elements) == 3


@pytest.mark.parametrize(
    "bad",
    [
        {"elements": [{"id": "a", "type": "text", "text": " ", "x": 0, "y": 0, "w": 1, "h": 1}]},  # empty, unbound
        {"elements": [{"id": "a", "type": "video", "x": 0, "y": 0, "w": 1, "h": 1}]},  # unknown type
        {"background": "red", "elements": []},  # not a hex colour
        {"elements": [{"id": "a", "type": "shape", "shape": "star", "x": 0, "y": 0, "w": 0, "h": 1}]},  # zero width
        {"elements": [{"id": "a b", "type": "shape", "shape": "star", "x": 0, "y": 0, "w": 1, "h": 1}]},  # bad id
        {"elements": [{"id": "a", "type": "shape", "shape": "star", "x": 0, "y": 0, "w": 1, "h": 1}] * 2},  # dup ids
        {"elements": [{"id": f"e{i}", "type": "shape", "shape": "rect", "x": 0, "y": 0, "w": 1, "h": 1} for i in range(41)]},
        {"elements": [], "script": "alert(1)"},  # unknown field
    ],
)
def test_layout_rejects(bad):
    with pytest.raises(ValueError):
        Layout.model_validate(bad)


# ------------------------------------------------------------ with database
integration = [pytest.mark.integration, requires_db]


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. لمى")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


@pytest.fixture
def image(migrated_dsn, db_client):
    """Upload + register an image for a teacher; returns its asset id."""

    def _image(t):
        path = f"{t['id']}/{uuid4()}.png"

        async def insert():
            conn = await asyncpg.connect(migrated_dsn)
            try:
                await conn.execute(
                    "insert into storage.objects (bucket_id, name, metadata) values ('teacher-assets', $1, $2::jsonb)",
                    path,
                    json.dumps({"size": 1000, "mimetype": "image/png"}),
                )
            finally:
                await conn.close()

        asyncio.run(insert())
        r = db_client.post("/api/v1/assets", headers=t["headers"], json={"storage_path": path, "file_name": "apples.png"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return _image


def _lesson(client, h):
    r = client.post("/api/v1/lessons", headers=h, json={"title": "الأرقام", "topic": "١ إلى ٥", "age_group": "age_4_5"})
    return r.json()["id"]


def _story(asset_id):
    slide = {**SLIDE, "elements": [*SLIDE["elements"], {"id": "img", "type": "image", "asset_id": asset_id, "x": 10, "y": 10, "w": 50, "h": 45}]}
    return {
        "type": "story",
        "title": "ثلاث تفاحات",
        "content": {"segments": [{"text": "عندي ثلاث تفاحات", "question": "كم تفاحة؟", "layouts": {"slide": slide}}]},
    }


@pytest.mark.integration
@requires_db
def test_activity_keeps_page_layouts(db_client, teacher, image):
    h = teacher["headers"]
    lid = _lesson(db_client, h)
    asset = image(teacher)
    r = db_client.post(f"/api/v1/lessons/{lid}/activities", headers=h, json=_story(asset))
    assert r.status_code == 201, r.text
    seg = db_client.get(f"/api/v1/lessons/{lid}", headers=h).json()["activities"][0]["content"]["segments"][0]
    elements = seg["layouts"]["slide"]["elements"]
    assert [e["id"] for e in elements] == ["t1", "n3", "s1", "img"]
    assert elements[3]["asset_id"] == asset and "worksheet" not in seg["layouts"]


@pytest.mark.integration
@requires_db
def test_page_cannot_use_unknown_or_foreign_image(db_client, teacher, image, make_teacher, make_token):
    h = teacher["headers"]
    lid = _lesson(db_client, h)
    other = {"id": make_teacher("أ. سارة")}
    other["headers"] = {"Authorization": f"Bearer {make_token(other['id'])}"}
    for asset in (str(uuid4()), image(other)):
        r = db_client.post(f"/api/v1/lessons/{lid}/activities", headers=h, json=_story(asset))
        assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == "unknown_asset"


@pytest.mark.integration
@requires_db
def test_update_layout_is_validated(db_client, teacher, image):
    h = teacher["headers"]
    lid = _lesson(db_client, h)
    act = db_client.post(f"/api/v1/lessons/{lid}/activities", headers=h, json=_story(image(teacher))).json()
    url = f"/api/v1/lessons/{lid}/activities/{act['id']}"
    bad = {"segments": [{"text": "x", "layouts": {"slide": {"elements": [{"id": "a", "type": "gif"}]}}}]}
    assert db_client.patch(url, headers=h, json={"content": bad}).status_code == 422
    good = {"segments": [{"text": "x", "layouts": {"worksheet": {"elements": [
        {"id": "d", "type": "shape", "shape": "rect", "dashed": True, "x": 10, "y": 10, "w": 30, "h": 30}
    ]}}}]}
    r = db_client.patch(url, headers=h, json={"content": good})
    assert r.status_code == 200 and r.json()["content"]["segments"][0]["layouts"]["worksheet"]["elements"][0]["dashed"]


@pytest.mark.integration
@requires_db
def test_library_save_list_reuse_and_privacy(db_client, teacher, image, make_teacher, make_token):
    h = teacher["headers"]
    asset = image(teacher)
    page = _story(asset)["content"]["segments"][0]
    r = db_client.post("/api/v1/saved-pages", headers=h, json={"title": "الرقم ثلاثة", "activity_type": "story", "page": page})
    assert r.status_code == 201, r.text
    saved = r.json()
    assert saved["page"]["layouts"]["slide"]["elements"][3]["asset_id"] == asset

    db_client.post("/api/v1/saved-pages", headers=h, json={"title": "سؤال", "activity_type": "qa_dialogue", "page": {"question": "كم؟"}})
    assert db_client.get("/api/v1/saved-pages", headers=h).json()["total"] == 2
    only_qa = db_client.get("/api/v1/saved-pages?activity_type=qa_dialogue", headers=h).json()
    assert [p["title"] for p in only_qa["items"]] == ["سؤال"]

    # reuse: the saved page goes into another lesson as-is
    lid = _lesson(db_client, h)
    reuse = {"type": "story", "title": "من مكتبتي", "content": {"segments": [saved["page"]]}}
    assert db_client.post(f"/api/v1/lessons/{lid}/activities", headers=h, json=reuse).status_code == 201

    renamed = db_client.patch(f"/api/v1/saved-pages/{saved['id']}", headers=h, json={"title": "ثلاثة ٣"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "ثلاثة ٣"

    other = {"Authorization": f"Bearer {make_token(make_teacher('أ. هند'))}"}
    assert db_client.get("/api/v1/saved-pages", headers=other).json()["total"] == 0
    assert db_client.get(f"/api/v1/saved-pages/{saved['id']}", headers=other).status_code == 404
    assert db_client.delete(f"/api/v1/saved-pages/{saved['id']}", headers=other).status_code == 404

    assert db_client.delete(f"/api/v1/saved-pages/{saved['id']}", headers=h).status_code == 204
    assert db_client.get(f"/api/v1/saved-pages/{saved['id']}", headers=h).status_code == 404


@pytest.mark.integration
@requires_db
@pytest.mark.parametrize(
    "body",
    [
        {"title": "x", "activity_type": "story", "page": {"question": "بدون نص"}},  # story page needs text
        {"title": "x", "activity_type": "song", "page": {"text": "a"}},
        {"title": " ", "activity_type": "story", "page": {"text": "a"}},
        {"title": "x", "activity_type": "story", "page": {"text": "a", "child_name": "سارة"}},
        {"title": "x", "activity_type": "story", "page": {"text": "a", "layouts": {"slide": {"elements": [
            {"id": "i", "type": "image", "asset_id": str(uuid4()), "x": 0, "y": 0, "w": 10, "h": 10}
        ]}}}},
    ],
)
def test_library_rejects_invalid_pages(db_client, teacher, body):
    r = db_client.post("/api/v1/saved-pages", headers=teacher["headers"], json=body)
    assert r.status_code == 422


@pytest.mark.integration
@requires_db
def test_library_empty_update_is_422(db_client, teacher):
    h = teacher["headers"]
    saved = db_client.post("/api/v1/saved-pages", headers=h, json={"title": "x", "activity_type": "interactive", "page": {"text": "قفوا"}}).json()
    assert db_client.patch(f"/api/v1/saved-pages/{saved['id']}", headers=h, json={}).status_code == 422
