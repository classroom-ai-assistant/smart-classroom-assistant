"""SQL for activities. Runs inside TeacherDatabase transactions, so RLS
applies; explicit teacher_id filters are a second guard.

Only activities PLACED in a lesson (order_index not null) belong to the
lesson's content. Unplaced rows are AI suggestions awaiting the teacher;
they are handled by app.modules.suggestions.
"""

from typing import Any
from uuid import UUID

import asyncpg

from app.database.rls_session import TeacherDatabase

ACTIVITY_COLUMNS = """
    a.id, a.lesson_id, a.type::text as type, a.title, a.content,
    a.approval_status::text as approval_status, a.origin::text as origin,
    a.order_index, a.created_at, a.updated_at
"""

PLACED_ACTIVITIES_SQL = f"""
select {ACTIVITY_COLUMNS}
from public.activities a
where a.lesson_id = $1 and a.teacher_id = $2 and a.order_index is not null
order by a.order_index
"""

# AI suggestions waiting for the teacher: never placed, never shown to children.
PENDING_SUGGESTIONS_SQL = f"""
select {ACTIVITY_COLUMNS}
from public.activities a
where a.lesson_id = $1 and a.teacher_id = $2 and a.order_index is null and a.approval_status = 'proposed'
order by a.created_at, a.id
"""

_LOCK_LESSON_SQL = "select 1 from public.lessons where id = $1 and teacher_id = $2 for update"
_TOUCH_LESSON_SQL = "update public.lessons set updated_at = now() where id = $1"

# Close gaps after a delete. The unique (lesson_id, order_index) constraint is
# deferrable, so positions can be rewritten inside one transaction.
_COMPACT_ORDER_SQL = """
update public.activities a
set order_index = r.position
from (
  select id, (row_number() over (order by order_index) - 1)::int as position
  from public.activities
  where lesson_id = $1 and order_index is not null
) r
where a.id = r.id and a.order_index is distinct from r.position
"""


async def _lock_lesson(conn: asyncpg.Connection, lesson_id: UUID, teacher_id: UUID) -> bool:
    return await conn.fetchval(_LOCK_LESSON_SQL, lesson_id, teacher_id) is not None


class ActivityRepository:
    def __init__(self, db: TeacherDatabase) -> None:
        self._db = db
        self._teacher_id = db.teacher.id

    async def get(self, lesson_id: UUID, activity_id: UUID) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"select {ACTIVITY_COLUMNS} from public.activities a "
                "where a.id = $1 and a.lesson_id = $2 and a.teacher_id = $3 and a.order_index is not null",
                activity_id,
                lesson_id,
                self._teacher_id,
            )
        return dict(row) if row else None

    async def create_manual(
        self, lesson_id: UUID, activity_type: str, title: str, content: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Teacher-written activity: approved on save, appended at the end.
        Returns None if the lesson does not exist for this teacher."""
        async with self._db.transaction() as conn:
            if not await _lock_lesson(conn, lesson_id, self._teacher_id):
                return None
            row = await conn.fetchrow(
                f"""
                insert into public.activities as a
                  (lesson_id, teacher_id, type, title, content, approval_status, origin, approved_at, order_index)
                values ($1, $2, $3::public.activity_type, $4, $5, 'approved', 'manual', now(),
                        (select coalesce(max(order_index) + 1, 0)
                           from public.activities where lesson_id = $1 and order_index is not null))
                returning {ACTIVITY_COLUMNS}
                """,
                lesson_id,
                self._teacher_id,
                activity_type,
                title,
                content,
            )
            await conn.execute(_TOUCH_LESSON_SQL, lesson_id)
        return dict(row) if row else None

    async def update(
        self, lesson_id: UUID, activity_id: UUID, title: str | None, content: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """A teacher's own edit counts as her approval (FR-021): the activity
        becomes approved, keeping its origin (manual or ai)."""
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"""
                update public.activities as a
                set title = coalesce($4, a.title),
                    content = coalesce($5::jsonb, a.content),
                    approval_status = 'approved',
                    approved_at = coalesce(a.approved_at, now())
                where a.id = $1 and a.lesson_id = $2 and a.teacher_id = $3 and a.order_index is not null
                returning {ACTIVITY_COLUMNS}
                """,
                activity_id,
                lesson_id,
                self._teacher_id,
                title,
                content,  # dict -> jsonb via the pool's codec; None keeps the current content
            )
            if row:
                await conn.execute(_TOUCH_LESSON_SQL, lesson_id)
        return dict(row) if row else None

    async def delete(self, lesson_id: UUID, activity_id: UUID) -> bool:
        async with self._db.transaction() as conn:
            if not await _lock_lesson(conn, lesson_id, self._teacher_id):
                return False
            deleted = await conn.fetchval(
                "delete from public.activities where id = $1 and lesson_id = $2 and teacher_id = $3 "
                "and order_index is not null returning id",
                activity_id,
                lesson_id,
                self._teacher_id,
            )
            if deleted is None:
                return False
            await conn.execute("set constraints public.activities_lesson_order_key deferred")
            await conn.execute(_COMPACT_ORDER_SQL, lesson_id)
            await conn.execute(_TOUCH_LESSON_SQL, lesson_id)
        return True

    async def reorder(self, lesson_id: UUID, activity_ids: list[UUID]) -> list[dict[str, Any]] | None:
        """Returns None if the lesson is missing; raises ValueError if the ids
        are not exactly the lesson's placed activities."""
        async with self._db.transaction() as conn:
            if not await _lock_lesson(conn, lesson_id, self._teacher_id):
                return None
            current = await conn.fetch(
                "select id from public.activities where lesson_id = $1 and order_index is not null",
                lesson_id,
            )
            if len(activity_ids) != len(set(activity_ids)) or {r["id"] for r in current} != set(activity_ids):
                raise ValueError("activity ids do not match the lesson's activities")
            await conn.execute("set constraints public.activities_lesson_order_key deferred")
            await conn.execute(
                """
                update public.activities a
                set order_index = (o.position - 1)::int
                from unnest($2::uuid[]) with ordinality as o(id, position)
                where a.id = o.id and a.lesson_id = $1
                """,
                lesson_id,
                activity_ids,
            )
            await conn.execute(_TOUCH_LESSON_SQL, lesson_id)
            rows = await conn.fetch(PLACED_ACTIVITIES_SQL, lesson_id, self._teacher_id)
        return [dict(r) for r in rows]
