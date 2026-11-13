"""Run queries as the signed-in teacher so Row Level Security applies.

The pool connects as a privileged database user, which would bypass RLS.
So every request opens a transaction and, before any query, switches to the
`authenticated` role and sets the JWT claims that `auth.uid()` reads. Both
are LOCAL to the transaction and reset automatically when it ends, so a
pooled connection never carries one teacher's identity into another's
request.

This is decision 4 of the Phase 1 design: even if a query here forgets the
owner filter, the database itself refuses to return another teacher's rows.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import asyncpg
from fastapi import Depends

from app.core.security import CurrentTeacher, get_current_teacher
from app.database.connection import get_pool


class _Executor(Protocol):
    async def execute(self, query: str, *args: object) -> str: ...


async def apply_rls_context(conn: _Executor, teacher: CurrentTeacher) -> None:
    claims = json.dumps({"sub": str(teacher.id), "role": "authenticated"})
    await conn.execute("set local role authenticated")
    await conn.execute("select set_config('request.jwt.claims', $1, true)", claims)


class TeacherDatabase:
    """Database access scoped to one teacher."""

    def __init__(self, pool: asyncpg.Pool, teacher: CurrentTeacher) -> None:
        self._pool = pool
        self.teacher = teacher

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await apply_rls_context(conn, self.teacher)
                yield conn


def get_teacher_database(
    pool: asyncpg.Pool = Depends(get_pool),
    teacher: CurrentTeacher = Depends(get_current_teacher),
) -> TeacherDatabase:
    return TeacherDatabase(pool, teacher)
