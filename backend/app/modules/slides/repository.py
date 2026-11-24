"""SQL for slides (RLS applies; teacher_id filters are a second guard).
Positions stay contiguous 0..n-1; the deferrable unique constraint lets a
transaction shift them."""

from typing import Any
from uuid import UUID

from app.database.rls_session import TeacherDatabase

COLUMNS = "s.id, s.lesson_id, s.order_index, s.layout, s.speech, s.question, s.created_at, s.updated_at"

SLIDES_SQL = f"""
select {COLUMNS} from public.slides s
where s.lesson_id = $1 and s.teacher_id = $2
order by s.order_index
"""

_COMPACT = """
update public.slides s set order_index = r.pos
from (select id, row_number() over (order by order_index) - 1 as pos
      from public.slides where lesson_id = $1) r
where s.id = r.id and s.order_index <> r.pos
"""


class SlideRepository:
    def __init__(self, db: TeacherDatabase) -> None:
        self._db = db
        self._teacher_id = db.teacher.id

    @property
    def db(self) -> TeacherDatabase:
        return self._db

    async def _lock_lesson(self, conn: Any, lesson_id: UUID) -> bool:
        found = await conn.fetchval(
            "select 1 from public.lessons where id = $1 and teacher_id = $2 for update", lesson_id, self._teacher_id
        )
        return found is not None

    async def _touch(self, conn: Any, lesson_id: UUID) -> None:
        await conn.execute("update public.lessons set updated_at = now() where id = $1", lesson_id)

    async def all(self, lesson_id: UUID) -> list[dict[str, Any]] | None:
        async with self._db.transaction() as conn:
            if not await conn.fetchval(
                "select 1 from public.lessons where id = $1 and teacher_id = $2", lesson_id, self._teacher_id
            ):
                return None
            return [dict(r) for r in await conn.fetch(SLIDES_SQL, lesson_id, self._teacher_id)]

    async def count(self, lesson_id: UUID) -> int:
        async with self._db.transaction() as conn:
            return await conn.fetchval("select count(*) from public.slides where lesson_id = $1", lesson_id)

    async def get(self, lesson_id: UUID, slide_id: UUID) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"select {COLUMNS} from public.slides s where s.id = $1 and s.lesson_id = $2 and s.teacher_id = $3",
                slide_id,
                lesson_id,
                self._teacher_id,
            )
        return dict(row) if row else None

    async def insert(
        self, lesson_id: UUID, position: int | None, layout: dict, speech: str | None, question: dict | None
    ) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            if not await self._lock_lesson(conn, lesson_id):
                return None
            await conn.execute("set constraints public.slides_lesson_order_key deferred")
            count = await conn.fetchval("select count(*) from public.slides where lesson_id = $1", lesson_id)
            pos = count if position is None else min(position, count)
            await conn.execute(
                "update public.slides set order_index = order_index + 1 where lesson_id = $1 and order_index >= $2",
                lesson_id,
                pos,
            )
            row = await conn.fetchrow(
                f"""
                insert into public.slides as s (lesson_id, teacher_id, order_index, layout, speech, question)
                values ($1, $2, $3, $4, $5, $6) returning {COLUMNS}
                """,
                lesson_id,
                self._teacher_id,
                pos,
                layout,
                speech,
                question,
            )
            await self._touch(conn, lesson_id)
        return dict(row)

    async def update(self, lesson_id: UUID, slide_id: UUID, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"layout", "speech", "question"}
        if not values or set(values) - allowed:
            raise ValueError("invalid slide columns")
        cols = sorted(values)
        sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(cols, start=4))
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"update public.slides as s set {sets} "
                f"where s.id = $1 and s.lesson_id = $2 and s.teacher_id = $3 returning {COLUMNS}",
                slide_id,
                lesson_id,
                self._teacher_id,
                *(values[c] for c in cols),
            )
            if row:
                await self._touch(conn, lesson_id)
        return dict(row) if row else None

    async def delete(self, lesson_id: UUID, slide_id: UUID) -> bool:
        async with self._db.transaction() as conn:
            if not await self._lock_lesson(conn, lesson_id):
                return False
            deleted = await conn.fetchval(
                "delete from public.slides where id = $1 and lesson_id = $2 and teacher_id = $3 returning id",
                slide_id,
                lesson_id,
                self._teacher_id,
            )
            if deleted:
                await conn.execute("set constraints public.slides_lesson_order_key deferred")
                await conn.execute(_COMPACT, lesson_id)
                await self._touch(conn, lesson_id)
        return deleted is not None

    async def reorder(self, lesson_id: UUID, slide_ids: list[UUID]) -> list[dict[str, Any]] | None:
        async with self._db.transaction() as conn:
            if not await self._lock_lesson(conn, lesson_id):
                return None
            current = {r["id"] for r in await conn.fetch("select id from public.slides where lesson_id = $1", lesson_id)}
            if len(slide_ids) != len(set(slide_ids)) or set(slide_ids) != current:
                raise ValueError("order must list every slide exactly once")
            await conn.execute("set constraints public.slides_lesson_order_key deferred")
            await conn.execute(
                """
                update public.slides s set order_index = n.pos - 1
                from unnest($2::uuid[]) with ordinality as n(id, pos)
                where s.id = n.id and s.lesson_id = $1
                """,
                lesson_id,
                slide_ids,
            )
            await self._touch(conn, lesson_id)
            return [dict(r) for r in await conn.fetch(SLIDES_SQL, lesson_id, self._teacher_id)]
