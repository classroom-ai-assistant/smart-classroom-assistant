"""The RLS context is set before any query, scoped to the transaction."""

import asyncio
import json
from uuid import uuid4

from app.core.security import CurrentTeacher
from app.database.rls_session import apply_rls_context


class RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, query: str, *args: object) -> str:
        self.calls.append((query, args))
        return "OK"


def test_switches_role_and_sets_claims_locally():
    teacher = CurrentTeacher(id=uuid4(), email="t@example.com")
    conn = RecordingConnection()

    asyncio.run(apply_rls_context(conn, teacher))

    (role_sql, _), (claims_sql, claims_args) = conn.calls
    assert role_sql == "set local role authenticated"
    # third argument `true` = local to the transaction, reset at commit/rollback
    assert "set_config('request.jwt.claims', $1, true)" in claims_sql
    claims = json.loads(claims_args[0])
    assert claims == {"sub": str(teacher.id), "role": "authenticated"}


def test_claims_carry_no_email_or_extra_data():
    teacher = CurrentTeacher(id=uuid4(), email="private@example.com")
    conn = RecordingConnection()
    asyncio.run(apply_rls_context(conn, teacher))
    assert "private@example.com" not in conn.calls[1][1][0]
