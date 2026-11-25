"""Stickers, animations, free image search and AI slide design.
AI and Pixabay are faked; database tests use the local Postgres."""

import asyncio
import json
from typing import Any
from uuid import uuid4

import asyncpg
import httpx
import pytest

from app.modules.images.client import PixabayClient
from app.modules.pages.layout import Layout
from app.modules.slides.ai import clean_slide
from app.modules.stickers.catalog import catalog, names
from app.shared.errors.exceptions import AiFailedError
from tests.db.fixtures import requires_db


# ------------------------------------------------------------- pure checks
def test_catalog_is_curated_and_pinned():
    items = catalog()
    assert 150 <= len(items) <= 250 and len(names()) == len(items)
    assert all(i["url"].startswith("https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@") for i in items)
    assert all("%20" in i["url"] or " " not in i["path"] for i in items)
    assert {"cat", "red_apple", "keycap_3", "sun"} <= names()


def test_layout_accepts_stickers_animation_transition_placeholder():
    layout = Layout.model_validate(
        {
            "transition": "zoom",
            "elements": [
                {"id": "c", "type": "sticker", "name": "cat", "x": 1, "y": 1, "w": 20, "h": 20,
                 "animation": {"effect": "bounce", "delay": 0.5, "duration": 0.8}},
                {"id": "p", "type": "placeholder", "query": "بطة صفراء", "x": 50, "y": 1, "w": 30, "h": 30},
            ],
        }
    )
    assert layout.transition == "zoom" and layout.elements[0].animation.effect == "bounce"


@pytest.mark.parametrize(
    "bad",
    [
        {"elements": [{"id": "c", "type": "sticker", "name": "dragon_unicorn", "x": 0, "y": 0, "w": 1, "h": 1}]},
        {"elements": [{"id": "c", "type": "sticker", "name": "cat", "x": 0, "y": 0, "w": 1, "h": 1, "animation": {"effect": "explode"}}]},
        {"transition": "cube", "elements": []},
        {"elements": [{"id": "p", "type": "placeholder", "query": "", "x": 0, "y": 0, "w": 1, "h": 1}]},
    ],
)
def test_layout_rejects(bad):
    with pytest.raises(ValueError):
        Layout.model_validate(bad)


def test_clean_slide_repairs_model_output():
    raw = {
        "layout": {
            "background": "#FCDC9F",
            "transition": "spiral",  # unknown -> fade
            "elements": [
                {"type": "text", "text": "حرف الباء", "font": "comic", "font_size": 99, "x": -20, "y": 5, "w": 300, "h": 20},
                {"id": "dup", "type": "sticker", "name": "duck", "x": 10, "y": 50, "w": 20, "h": 20,
                 "animation": {"effect": "pop", "delay": 99}},
                {"id": "dup", "type": "sticker", "name": "not_a_sticker", "x": 0, "y": 0, "w": 1, "h": 1},
                {"type": "image", "asset_id": str(uuid4())},  # models may not place real files
                {"type": "placeholder", "query": "بطة صفراء حقيقية", "x": 60, "y": 40, "w": 30, "h": 40},
            ],
        },
        "speech": "هيا نتعلم حرف الباء",
        "question": {"question": "ما أول حرف في بطة؟", "expected_answers": ["باء"], "extra": 1},
    }
    d = clean_slide(raw)
    assert d is not None and d.layout.transition == "fade"
    types = [e.type for e in d.layout.elements]
    assert types == ["text", "sticker", "placeholder"]
    t = d.layout.elements[0]
    assert t.font == "tajawal" and t.font_size == 20 and t.x == 0 and t.w <= 100
    assert d.layout.elements[1].animation.delay == 10
    assert d.question.question == "ما أول حرف في بطة؟"


def test_clean_slide_drops_empty():
    assert clean_slide({"layout": {"elements": [{"type": "video"}]}}) is None
    assert clean_slide("nonsense") is None


def test_pixabay_client_safe_search_cache_and_host_check():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "pixabay.com" and "id" not in request.url.params:
            return httpx.Response(200, json={"totalHits": 1, "hits": [
                {"id": 7, "webformatURL": "https://pixabay.com/get/a.jpg", "webformatWidth": 640, "webformatHeight": 480,
                 "tags": "duck", "user": "anna", "pageURL": "https://pixabay.com/photos/duck-7/"}]})
        if request.url.host == "pixabay.com":
            url = "https://cdn.pixabay.com/photo/big.jpg" if request.url.params["id"] == "7" else "https://evil.example/x.jpg"
            return httpx.Response(200, json={"hits": [{"id": 7, "largeImageURL": url}]})
        return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"})

    client = PixabayClient("test-key-not-real", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    r1 = asyncio.run(client.search("بطة", 1, "all"))
    asyncio.run(client.search("بطة", 1, "all"))  # cached
    assert r1["items"][0]["author"] == "anna" and len(calls) == 1
    assert calls[0].url.params["safesearch"] == "true"
    content, ctype = asyncio.run(client.file(7))
    assert ctype == "image/jpeg" and content.startswith(b"\xff\xd8")
    with pytest.raises(AiFailedError):
        asyncio.run(client.file(8))  # not a pixabay host


# ------------------------------------------------------------- API
class FakeAi:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    async def generate_json(self, system: str, prompt: str) -> Any:
        self.prompts.append((system, prompt))
        return self.replies.pop(0)


class FakePixabay:
    async def search(self, query, page, image_type):
        return {"items": [{"id": 1, "preview_url": "https://pixabay.com/get/p.jpg", "width": 640, "height": 480,
                           "tags": query, "author": "anna", "page_url": "https://pixabay.com/x"}], "total": 1}

    async def file(self, image_id):
        return b"\xff\xd8jpeg", "image/jpeg"


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. لمى")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


def _lesson(client, h):
    return client.post("/api/v1/lessons", headers=h, json={"title": "حرف الباء", "topic": "الحروف", "age_group": "age_4_5"}).json()


SLIDE = {
    "layout": {"background": "#FCDC9F", "transition": "fade", "elements": [
        {"id": "t", "type": "text", "text": "ب", "font": "lalezar", "font_size": 18, "x": 30, "y": 20, "w": 40, "h": 40,
         "animation": {"effect": "zoom", "delay": 0, "duration": 0.8}},
        {"id": "s", "type": "sticker", "name": "duck", "x": 70, "y": 50, "w": 20, "h": 30}]},
    "speech": "هذا حرف الباء", "question": None,
}


@pytest.mark.integration
@requires_db
def test_stickers_endpoint(db_client, teacher):
    r = db_client.get("/api/v1/stickers", headers=teacher["headers"])
    assert r.status_code == 200 and len(r.json()["items"]) == len(catalog()) and "MIT" in r.json()["credit"]
    assert db_client.get("/api/v1/stickers").status_code == 401


@pytest.mark.integration
@requires_db
def test_generate_returns_drafts_only(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    ai = FakeAi({"slides": [SLIDE, {"layout": {"elements": []}}, SLIDE]})
    db_client.app.state.ai_client = ai
    r = db_client.post(f"/api/v1/lessons/{lesson['id']}/slides/generate", headers=h, json={"template": "letter", "count": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["slides"]) == 2 and body["requested"] == 3
    assert body["slides"][0]["layout"]["elements"][1]["name"] == "duck"
    system, prompt = ai.prompts[0]
    assert "duck=بطة" in system and "حرف الباء" in prompt and str(teacher["id"]) not in system + prompt
    # nothing was saved
    assert db_client.get(f"/api/v1/lessons/{lesson['id']}/slides", headers=h).json() == []
    # a draft can be saved as is
    assert db_client.post(f"/api/v1/lessons/{lesson['id']}/slides", headers=h, json=body["slides"][0]).status_code == 201


@pytest.mark.integration
@requires_db
def test_generate_fails_cleanly(db_client, teacher):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    db_client.app.state.ai_client = FakeAi({"slides": []}, {"oops": 1})
    r = db_client.post(f"/api/v1/lessons/{lesson['id']}/slides/generate", headers=h, json={})
    assert r.status_code == 502 and r.json()["error"]["code"] == "ai_failed"


@pytest.mark.integration
@requires_db
@pytest.mark.parametrize(
    ("action", "reply", "check"),
    [
        ("speech", {"speech": "يا أطفال، هذا حرف الباء"}, lambda b: b["speech"].startswith("يا أطفال")),
        ("question", {"question": {"question": "ما هذا الحرف؟", "expected_answers": ["باء"]}}, lambda b: b["question"]["question"] == "ما هذا الحرف؟"),
        ("simplify", {"texts": {"t": "باء"}}, lambda b: b["layout"]["elements"][0]["text"] == "باء"),
    ],
)
def test_assist(db_client, teacher, action, reply, check):
    h = teacher["headers"]
    lesson = _lesson(db_client, h)
    db_client.app.state.ai_client = FakeAi(reply)
    r = db_client.post(f"/api/v1/lessons/{lesson['id']}/slides/assist", headers=h,
                       json={"action": action, "layout": SLIDE["layout"]})
    assert r.status_code == 200, r.text and check(r.json())
    assert check(r.json())


@pytest.mark.integration
@requires_db
def test_ai_endpoints_respect_lesson_ownership(db_client, teacher, make_teacher, make_token):
    lesson = _lesson(db_client, teacher["headers"])
    o = {"Authorization": f"Bearer {make_token(make_teacher('أ. هند'))}"}
    ai = FakeAi()
    db_client.app.state.ai_client = ai
    assert db_client.post(f"/api/v1/lessons/{lesson['id']}/slides/generate", headers=o, json={}).status_code == 404
    assert db_client.post(f"/api/v1/lessons/{lesson['id']}/slides/assist", headers=o,
                          json={"action": "speech", "layout": {"elements": []}}).status_code == 404
    assert ai.prompts == []


@pytest.mark.integration
@requires_db
def test_image_search_and_library_import(db_client, teacher, migrated_dsn):
    h = teacher["headers"]
    assert db_client.get("/api/v1/images/search?q=بطة", headers=h).status_code == 503  # no key configured
    db_client.app.state.image_search = FakePixabay()
    r = db_client.get("/api/v1/images/search?q=بطة", headers=h)
    assert r.status_code == 200 and r.json()["items"][0]["author"] == "anna" and r.json()["credit"] == "Pixabay"
    f = db_client.get("/api/v1/images/pixabay/1/file", headers=h)
    assert f.status_code == 200 and f.headers["content-type"] == "image/jpeg"
    assert db_client.get("/api/v1/images/search?q=", headers=h).status_code == 422

    # the browser stores it in ملفاتي and registers it with the credit
    path = f"{teacher['id']}/{uuid4()}.jpg"

    async def upload():
        conn = await asyncpg.connect(migrated_dsn)
        try:
            await conn.execute(
                "insert into storage.objects (bucket_id, name, metadata) values ('teacher-assets', $1, $2::jsonb)",
                path, json.dumps({"size": 6, "mimetype": "image/jpeg"}),
            )
        finally:
            await conn.close()

    asyncio.run(upload())
    a = db_client.post("/api/v1/assets", headers=h, json={"storage_path": path, "file_name": "duck.jpg",
                                                         "source": "library", "attribution": "anna — Pixabay"})
    assert a.status_code == 201 and a.json()["source"] == "library" and a.json()["attribution"] == "anna — Pixabay"
