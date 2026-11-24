"""Migrations 0007/0008: assets, saved pages and the teacher-assets bucket,
checked as the `authenticated` role so RLS applies. Local Postgres only."""

import asyncio
import json
from uuid import UUID, uuid4

import asyncpg
import pytest

from tests.db.fixtures import requires_db

pytestmark = [pytest.mark.integration, requires_db]


async def _as_teacher(dsn: str, teacher_id: UUID, sql: str, *args):
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            await conn.execute("set local role authenticated")
            await conn.execute(
                "select set_config('request.jwt.claims', $1, true)", json.dumps({"sub": str(teacher_id)})
            )
            return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def run(dsn, tid, sql, *args):
    return asyncio.run(_as_teacher(dsn, tid, sql, *args))


INSERT_ASSET = """
insert into public.assets (teacher_id, kind, storage_path, file_name, mime_type, size_bytes)
values ($1, $2::public.asset_kind, $3, 'apple.png', $4, $5) returning id
"""


def test_teacher_stores_and_sees_only_her_assets(migrated_dsn, make_teacher):
    a, b = make_teacher("أ. نورة"), make_teacher("أ. سارة")
    run(migrated_dsn, a, INSERT_ASSET, a, "image", f"{a}/{uuid4()}.png", "image/png", 2048)
    assert len(run(migrated_dsn, a, "select id from public.assets")) == 1
    assert run(migrated_dsn, b, "select id from public.assets") == []


@pytest.mark.parametrize(
    ("kind", "mime", "size", "own_folder"),
    [
        ("image", "image/png", 2048, False),  # path in another teacher's folder
        ("image", "application/pdf", 2048, True),  # mime does not match kind
        ("image", "image/png", 10485761, True),  # image over 10 MB
        ("video", "video/mp4", 52428801, True),  # video over 50 MB
        ("pdf", "image/svg+xml", 10, True),  # not an allowed type
    ],
)
def test_invalid_assets_are_rejected(migrated_dsn, make_teacher, kind, mime, size, own_folder):
    a = make_teacher()
    folder = a if own_folder else uuid4()
    with pytest.raises((asyncpg.CheckViolationError, asyncpg.InsufficientPrivilegeError)):
        run(migrated_dsn, a, INSERT_ASSET, a, kind, f"{folder}/{uuid4()}.bin", mime, size)


def test_cannot_insert_asset_for_another_teacher(migrated_dsn, make_teacher):
    a, b = make_teacher(), make_teacher()
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(migrated_dsn, a, INSERT_ASSET, b, "image", f"{b}/{uuid4()}.png", "image/png", 10)


def test_assets_cannot_be_updated(migrated_dsn, make_teacher):
    a = make_teacher()
    run(migrated_dsn, a, INSERT_ASSET, a, "pdf", f"{a}/{uuid4()}.pdf", "application/pdf", 10)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(migrated_dsn, a, "update public.assets set file_name = 'x'")


def test_saved_pages_are_private(migrated_dsn, make_teacher):
    a, b = make_teacher(), make_teacher()
    run(
        migrated_dsn,
        a,
        "insert into public.saved_pages (teacher_id, title, activity_type, page) values ($1, 'الرقم ثلاثة', 'story', $2::jsonb)",
        a,
        json.dumps({"text": "ثلاث تفاحات"}),
    )
    assert len(run(migrated_dsn, a, "select id from public.saved_pages")) == 1
    assert run(migrated_dsn, b, "select id from public.saved_pages") == []
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            migrated_dsn,
            a,
            "insert into public.saved_pages (teacher_id, title, activity_type, page) values ($1, 'x', 'story', '[]'::jsonb)",
            a,
        )


def test_storage_objects_only_in_own_folder(migrated_dsn, make_teacher):
    a, b = make_teacher(), make_teacher()
    ins = "insert into storage.objects (bucket_id, name) values ('teacher-assets', $1)"
    run(migrated_dsn, a, ins, f"{a}/{uuid4()}.png")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(migrated_dsn, a, ins, f"{b}/{uuid4()}.png")
    assert len(run(migrated_dsn, a, "select id from storage.objects")) == 1
    assert run(migrated_dsn, b, "select id from storage.objects") == []


def test_bucket_is_private(migrated_dsn):
    async def check():
        conn = await asyncpg.connect(migrated_dsn)
        try:
            return await conn.fetchrow("select public, file_size_limit from storage.buckets where id = 'teacher-assets'")
        finally:
            await conn.close()

    row = asyncio.run(check())
    assert row["public"] is False and row["file_size_limit"] == 52428800
