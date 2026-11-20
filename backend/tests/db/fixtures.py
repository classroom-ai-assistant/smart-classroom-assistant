"""Real-database fixtures for integration tests.

Set TEST_ADMIN_DATABASE_URL to a LOCAL Postgres superuser connection, e.g.
    postgresql://postgres@127.0.0.1:5432/postgres
A throwaway database is created, the Supabase stub and every migration in
supabase/migrations are applied, and the database is dropped afterwards.
Never point this at Supabase or any shared database.

The API then runs exactly as in production: role `authenticated` + JWT claims,
so Row Level Security is enforced by Postgres, not by the test.
"""

import asyncio
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import TokenVerifier
from app.main import create_app

ADMIN_DSN = os.environ.get("TEST_ADMIN_DATABASE_URL")
REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = sorted((REPO_ROOT / "supabase" / "migrations").glob("*.sql"))
STUB = Path(__file__).with_name("supabase_stub.sql")

requires_db = pytest.mark.skipif(not ADMIN_DSN, reason="TEST_ADMIN_DATABASE_URL not set")


def _dsn_for(database: str) -> str:
    base, _, _ = ADMIN_DSN.rpartition("/")
    return f"{base}/{database}"


async def _create_database(name: str) -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute(f'create database "{name}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(_dsn_for(name))
    try:
        await conn.execute(STUB.read_text())
        for migration in MIGRATIONS:
            await conn.execute(migration.read_text())
    finally:
        await conn.close()


async def _drop_database(name: str) -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute(f'drop database if exists "{name}" with (force)')
    finally:
        await admin.close()


@pytest.fixture(scope="session")
def migrated_dsn() -> Iterator[str]:
    name = f"sca_test_{uuid.uuid4().hex[:10]}"
    asyncio.run(_create_database(name))
    try:
        yield _dsn_for(name)
    finally:
        asyncio.run(_drop_database(name))


@pytest.fixture
def make_teacher(migrated_dsn: str) -> Iterator[Callable[[str], UUID]]:
    """Insert a fictional auth user (the sign-up trigger creates the profile)."""
    created: list[UUID] = []

    async def _insert(teacher_id: UUID, name: str) -> None:
        conn = await asyncpg.connect(migrated_dsn)
        try:
            await conn.execute(
                """insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
                                           raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
                   values ('00000000-0000-0000-0000-000000000000', $1, 'authenticated', 'authenticated',
                           $2, '', '{}', jsonb_build_object('display_name', $3::text), now(), now())""",
                teacher_id,
                f"{teacher_id.hex[:8]}@example.com",
                name,
            )
        finally:
            await conn.close()

    def _make(name: str = "معلمة تجريبية") -> UUID:
        teacher_id = uuid.uuid4()
        asyncio.run(_insert(teacher_id, name))
        created.append(teacher_id)
        return teacher_id

    yield _make

    async def _cleanup() -> None:
        conn = await asyncpg.connect(migrated_dsn)
        try:
            await conn.execute("delete from auth.users where id = any($1::uuid[])", created)
        finally:
            await conn.close()

    if created:
        asyncio.run(_cleanup())


@pytest.fixture
def db_client(migrated_dsn: str, verifier: TokenVerifier) -> Iterator[TestClient]:
    settings = Settings(
        app_env="test",
        supabase_url="https://test-project.supabase.co",
        database_url=migrated_dsn,
        db_pool_min_size=1,
        db_pool_max_size=4,
    )
    app = create_app(settings, connect_db=True)
    app.state.token_verifier = verifier
    with TestClient(app) as client:
        yield client
