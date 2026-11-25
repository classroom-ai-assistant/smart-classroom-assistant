"""SQL for saved slides (RLS: own rows only)."""

from typing import Any
from uuid import UUID

from app.database.rls_session import TeacherDatabase

COLUMNS = "id, title, layout, speech, question, created_at, updated_at"


class SavedSlideRepository:
    def __init__(self, db: TeacherDatabase) -> None:
        self._db = db
        self._teacher_id = db.teacher.id

    async def page(self, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        async with self._db.transaction() as conn:
            rows = await conn.fetch(
                f"select {COLUMNS} from public.saved_slides where teacher_id = $1 "
                "order by updated_at desc, id limit $2 offset $3",
                self._teacher_id,
                limit,
                offset,
            )
            total = await conn.fetchval("select count(*) from public.saved_slides where teacher_id = $1", self._teacher_id)
        return [dict(r) for r in rows], total

    async def get(self, saved_id: UUID) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"select {COLUMNS} from public.saved_slides where id = $1 and teacher_id = $2", saved_id, self._teacher_id
            )
        return dict(row) if row else None

    async def save_from_slide(self, lesson_id: UUID, slide_id: UUID, title: str) -> dict[str, Any] | None:
        """Copy a slide of the teacher's lesson; None if there is no such slide."""
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"""
                insert into public.saved_slides (teacher_id, title, layout, speech, question)
                select s.teacher_id, $4, s.layout, s.speech, s.question
                from public.slides s
                where s.id = $1 and s.lesson_id = $2 and s.teacher_id = $3
                returning {COLUMNS}
                """,
                slide_id,
                lesson_id,
                self._teacher_id,
                title,
            )
        return dict(row) if row else None

    async def rename(self, saved_id: UUID, title: str) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"update public.saved_slides set title = $3 where id = $1 and teacher_id = $2 returning {COLUMNS}",
                saved_id,
                self._teacher_id,
                title,
            )
        return dict(row) if row else None

    async def delete(self, saved_id: UUID) -> bool:
        async with self._db.transaction() as conn:
            deleted = await conn.fetchval(
                "delete from public.saved_slides where id = $1 and teacher_id = $2 returning id", saved_id, self._teacher_id
            )
        return deleted is not None
