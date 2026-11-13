"""Repository against a real dev database, with RLS.

Skipped unless TEST_DATABASE_URL points at a DEV Supabase database that
already has the Phase 1 migrations. Each test runs inside a transaction
that is rolled back, so nothing is left behind. Never point this at
production data.
"""

import os
from uuid import uuid4

import asyncpg
import pytest

from app.core.security import CurrentTeacher
from app.database.rls_session import apply_rls_context

pytestmark = pytest.mark.integration

DSN = os.environ.get("TEST_DATABASE_URL")
if not DSN:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)


async def _run(check):
    conn = await asyncpg.connect(DSN, statement_cache_size=0)
    tx = conn.transaction()
    await tx.start()
    try:
        a, b = uuid4(), uuid4()
        for tid, email in ((a, "int-a@example.com"), (b, "int-b@example.com")):
            await conn.execute(
                """insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
                                          raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
                   values ('00000000-0000-0000-0000-000000000000', $1, 'authenticated', 'authenticated',
                           $2, '', '{}', '{}', now(), now())""",
                tid,
                email,
            )
        await apply_rls_context(conn, CurrentTeacher(id=a, email=None))
        await check(conn, a, b)
    finally:
        await tx.rollback()
        await conn.close()


def test_teacher_sees_only_her_own_profile_under_rls():
    async def check(conn, a, b):
        ids = [r["id"] for r in await conn.fetch("select id from public.teachers")]
        assert ids == [a]
        assert await conn.fetchval("select count(*) from public.teacher_settings where teacher_id = $1", b) == 0

    import asyncio

    asyncio.run(_run(check))


def test_teacher_cannot_update_another_teachers_settings():
    async def check(conn, a, b):
        result = await conn.execute("update public.teacher_settings set voice_volume = 1 where teacher_id = $1", b)
        assert result == "UPDATE 0"

    import asyncio

    asyncio.run(_run(check))
