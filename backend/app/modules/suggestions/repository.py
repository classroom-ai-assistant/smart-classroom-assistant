"""SQL for AI suggestions: activities with origin 'ai', status 'proposed' and
no position. Approving one places it at the end of the lesson; rejecting one
deletes it. Runs inside TeacherDatabase transactions (RLS applies)."""

from typing import Any
from uuid import UUID

from app.database.rls_session import TeacherDatabase
from app.modules.activities.repository import ACTIVITY_COLUMNS

_PENDING = "a.order_index is null and a.approval_status = 'proposed'"


class SuggestionRepository:
    def __init__(self, db: TeacherDatabase) -> None:
        self._db = db
        self._teacher_id = db.teacher.id

    async def lesson_context(self, lesson_id: UUID) -> dict[str, Any] | None:
        """Lesson fields the AI may see, plus the number of pending suggestions."""
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"""
                select l.title, l.topic, l.age_group::text as age_group,
                       (select count(*) from public.activities a
                         where a.lesson_id = l.id and {_PENDING})::int as pending
                from public.lessons l where l.id = $1 and l.teacher_id = $2
                """,
                lesson_id,
                self._teacher_id,
            )
        return dict(row) if row else None

    async def get_pending(self, lesson_id: UUID, suggestion_id: UUID) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"select {ACTIVITY_COLUMNS} from public.activities a "
                f"where a.id = $1 and a.lesson_id = $2 and a.teacher_id = $3 and {_PENDING}",
                suggestion_id,
                lesson_id,
                self._teacher_id,
            )
        return dict(row) if row else None

    async def insert(self, lesson_id: UUID, items: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        """Store suggestions; None if the lesson no longer exists."""
        async with self._db.transaction() as conn:
            exists = await conn.fetchval(
                "select 1 from public.lessons where id = $1 and teacher_id = $2 for update",
                lesson_id,
                self._teacher_id,
            )
            if exists is None:
                return None
            rows = []
            for item in items:
                rows.append(
                    await conn.fetchrow(
                        f"""
                        insert into public.activities as a
                          (lesson_id, teacher_id, type, title, content, approval_status, origin)
                        values ($1, $2, $3::public.activity_type, $4, $5, 'proposed', 'ai')
                        returning {ACTIVITY_COLUMNS}
                        """,
                        lesson_id,
                        self._teacher_id,
                        item["type"],
                        item["title"],
                        item["content"],
                    )
                )
        return [dict(r) for r in rows]

    async def approve(
        self, lesson_id: UUID, suggestion_id: UUID, title: str | None, content: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Approve (optionally with the teacher's edits) and append to the lesson."""
        async with self._db.transaction() as conn:
            exists = await conn.fetchval(
                "select 1 from public.lessons where id = $1 and teacher_id = $2 for update",
                lesson_id,
                self._teacher_id,
            )
            if exists is None:
                return None
            row = await conn.fetchrow(
                f"""
                update public.activities as a
                set title = coalesce($4, a.title),
                    content = coalesce($5::jsonb, a.content),
                    approval_status = 'approved',
                    approved_at = now(),
                    order_index = (select coalesce(max(order_index) + 1, 0)
                                     from public.activities where lesson_id = $2 and order_index is not null)
                where a.id = $1 and a.lesson_id = $2 and a.teacher_id = $3 and {_PENDING}
                returning {ACTIVITY_COLUMNS}
                """,
                suggestion_id,
                lesson_id,
                self._teacher_id,
                title,
                content,
            )
            if row:
                await conn.execute("update public.lessons set updated_at = now() where id = $1", lesson_id)
        return dict(row) if row else None

    async def reject(self, lesson_id: UUID, suggestion_id: UUID) -> bool:
        async with self._db.transaction() as conn:
            deleted = await conn.fetchval(
                f"delete from public.activities a where a.id = $1 and a.lesson_id = $2 "
                f"and a.teacher_id = $3 and {_PENDING} returning a.id",
                suggestion_id,
                lesson_id,
                self._teacher_id,
            )
        return deleted is not None
