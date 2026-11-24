"""Teacher files API against a real Postgres with the real migrations and RLS.
"Uploads" are simulated by inserting the storage.objects row Supabase would
create. Skipped unless TEST_ADMIN_DATABASE_URL points at a local Postgres."""

import asyncio
import json
from uuid import uuid4

import asyncpg
import pytest

from tests.db.fixtures import requires_db

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture
def upload(migrated_dsn):
    """Pretend the browser uploaded a file; returns its storage path."""

    def _upload(folder, mime="image/png", size=2048, ext="png"):
        path = f"{folder}/{uuid4()}.{ext}"

        async def insert():
            conn = await asyncpg.connect(migrated_dsn)
            try:
                await conn.execute(
                    "insert into storage.objects (bucket_id, name, metadata) values ('teacher-assets', $1, $2::jsonb)",
                    path,
                    json.dumps({"size": size, "mimetype": mime}),
                )
            finally:
                await conn.close()

        asyncio.run(insert())
        return path

    return _upload


@pytest.fixture
def teacher(make_teacher, make_token):
    tid = make_teacher("أ. ريم")
    return {"id": tid, "headers": {"Authorization": f"Bearer {make_token(tid)}"}}


def _register(client, headers, path, **extra):
    return client.post("/api/v1/assets", headers=headers, json={"storage_path": path, "file_name": "تفاحة.png", **extra})


def test_register_takes_type_and_size_from_storage(db_client, teacher, upload):
    path = upload(teacher["id"], mime="image/jpeg", size=4096, ext="jpg")
    r = _register(db_client, teacher["headers"], path, width=800, height=600)
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["kind"], a["mime_type"], a["size_bytes"], a["source"]) == ("image", "image/jpeg", 4096, "upload")
    assert (a["width"], a["height"], a["file_name"]) == (800, 600, "تفاحة.png")


def test_list_filter_and_paging(db_client, teacher, upload):
    h = teacher["headers"]
    for mime, ext in [("image/png", "png"), ("application/pdf", "pdf"), ("video/mp4", "mp4")]:
        assert _register(db_client, h, upload(teacher["id"], mime=mime, ext=ext)).status_code == 201
    all_ = db_client.get("/api/v1/assets", headers=h).json()
    assert all_["total"] == 3 and all_["items"][0]["kind"] == "video"  # newest first
    assert [x["kind"] for x in db_client.get("/api/v1/assets?kind=pdf", headers=h).json()["items"]] == ["pdf"]
    assert db_client.get("/api/v1/assets?offset=10", headers=h).json() == {"items": [], "total": 3}
    assert db_client.get("/api/v1/assets?kind=song", headers=h).status_code == 422


def test_pdf_has_no_dimensions(db_client, teacher, upload):
    r = _register(db_client, teacher["headers"], upload(teacher["id"], mime="application/pdf", ext="pdf"), width=10, height=10)
    assert r.status_code == 201 and r.json()["width"] is None


@pytest.mark.parametrize(
    ("mime", "size", "kind"),
    [("image/svg+xml", 100, "not_allowed"), ("image/png", 10485761, "too_large"), ("video/mp4", 52428801, "too_large")],
)
def test_bad_files_are_rejected(db_client, teacher, upload, mime, size, kind):
    r = _register(db_client, teacher["headers"], upload(teacher["id"], mime=mime, size=size))
    assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == kind
    assert db_client.get("/api/v1/assets", headers=teacher["headers"]).json()["total"] == 0


def test_missing_upload_is_404(db_client, teacher):
    r = _register(db_client, teacher["headers"], f"{teacher['id']}/{uuid4()}.png")
    assert r.status_code == 404


def test_cannot_register_another_teachers_file(db_client, teacher, upload, make_teacher):
    other = make_teacher("أ. هند")
    r = _register(db_client, teacher["headers"], upload(other))
    assert r.status_code == 422 and r.json()["error"]["details"][0]["type"] == "wrong_folder"


def test_register_twice_is_conflict(db_client, teacher, upload):
    path = upload(teacher["id"])
    assert _register(db_client, teacher["headers"], path).status_code == 201
    assert _register(db_client, teacher["headers"], path).status_code == 409


def test_delete_returns_path_and_is_private(db_client, teacher, upload, make_teacher, make_token):
    path = upload(teacher["id"])
    asset = _register(db_client, teacher["headers"], path).json()
    other = {"Authorization": f"Bearer {make_token(make_teacher('أ. منى'))}"}
    assert db_client.get("/api/v1/assets", headers=other).json()["total"] == 0
    assert db_client.delete(f"/api/v1/assets/{asset['id']}", headers=other).status_code == 404
    r = db_client.delete(f"/api/v1/assets/{asset['id']}", headers=teacher["headers"])
    assert r.status_code == 200 and r.json() == {"storage_path": path}
    assert db_client.delete(f"/api/v1/assets/{asset['id']}", headers=teacher["headers"]).status_code == 404


@pytest.mark.parametrize(
    "body",
    [{"storage_path": "x/y.png"}, {"storage_path": "a/b.png", "file_name": " "}, {"storage_path": "a/b.png", "file_name": "x", "kind": "image"}],
)
def test_invalid_body(db_client, teacher, body):
    assert db_client.post("/api/v1/assets", headers=teacher["headers"], json=body).status_code == 422


def test_requires_token(db_client):
    assert db_client.get("/api/v1/assets").status_code == 401
