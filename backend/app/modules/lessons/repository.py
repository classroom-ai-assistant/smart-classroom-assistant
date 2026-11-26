"""SQL for lessons. Runs inside TeacherDatabase transactions (RLS applies);
explicit teacher_id filters are a second guard. Status comes from the
lessons_with_status view and is never stored (BRL-12)."""

from typing import Any
from uuid import UUID

from app.database.rls_session import TeacherDatabase
from app.modules.activities.repository import PENDING_SUGGESTIONS_SQL, PLACED_ACTIVITIES_SQL
from app.modules.slides.repository import SLIDES_SQL

_SUMMARY_COLUMNS = """
    l.id, l.title, l.topic, l.age_group::text as age_group, l.status,
    l.copied_from_lesson_id, l.created_at, l.updated_at,
    (select count(*) from public.activities a
      where a.lesson_id = l.id and a.order_index is not null)::int as activity_count,
    (select count(*) from public.slides s where s.lesson_id = l.id)::int as slide_count
"""

UPDATABLE_LESSON_COLUMNS = frozenset({"title", "topic", "age_group"})
COPY_PREFIX = "نسخة من "


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class LessonRepository:
    def __init__(self, db: TeacherDatabase) -> None:
        self._db = db
        self._teacher_id = db.teacher.id

    async def list(self, search: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        pattern = f"%{escape_like(search)}%" if search else None
        async with self._db.transaction() as conn:
            rows = await conn.fetch(
                f"""
                select {_SUMMARY_COLUMNS}, count(*) over () as total
                from public.lessons_with_status l
                where l.teacher_id = $1 and ($2::text is null or l.title ilike $2 escape '\\')
                order by l.updated_at desc, l.id
                limit $3 offset $4
                """,
                self._teacher_id,
                pattern,
                limit,
                offset,
            )
            if rows:
                total = rows[0]["total"]
            else:
                total = await conn.fetchval(
                    "select count(*) from public.lessons l "
                    "where l.teacher_id = $1 and ($2::text is null or l.title ilike $2 escape '\\')",
                    self._teacher_id,
                    pattern,
                )
        return [{k: v for k, v in r.items() if k != "total"} for r in rows], int(total)

    async def get(self, lesson_id: UUID) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"select {_SUMMARY_COLUMNS} from public.lessons_with_status l where l.id = $1 and l.teacher_id = $2",
                lesson_id,
                self._teacher_id,
            )
            if row is None:
                return None
            activities = await conn.fetch(PLACED_ACTIVITIES_SQL, lesson_id, self._teacher_id)
            suggestions = await conn.fetch(PENDING_SUGGESTIONS_SQL, lesson_id, self._teacher_id)
            slides = await conn.fetch(SLIDES_SQL, lesson_id, self._teacher_id)
        return {
            **dict(row),
            "slides": [dict(s) for s in slides],
            "activities": [dict(a) for a in activities],
            "suggestions": [dict(s) for s in suggestions],
        }

    async def create(self, title: str, topic: str, age_group: str) -> UUID:
        async with self._db.transaction() as conn:
            return await conn.fetchval(
                "insert into public.lessons (teacher_id, title, topic, age_group) "
                "values ($1, $2, $3, $4::public.age_group) returning id",
                self._teacher_id,
                title,
                topic,
                age_group,
            )

    async def update(self, lesson_id: UUID, values: dict[str, Any]) -> bool:
        unknown = set(values) - UPDATABLE_LESSON_COLUMNS
        if unknown or not values:
            raise ValueError(f"invalid lesson columns: {sorted(unknown)}")
        columns = sorted(values)
        assignments = ", ".join(
            f"{c} = ${i}" + ("::public.age_group" if c == "age_group" else "") for i, c in enumerate(columns, start=3)
        )
        async with self._db.transaction() as conn:
            result = await conn.execute(
                f"update public.lessons set {assignments} where id = $1 and teacher_id = $2",
                lesson_id,
                self._teacher_id,
                *(values[c] for c in columns),
            )
        return result == "UPDATE 1"

    async def delete(self, lesson_id: UUID) -> bool:
        async with self._db.transaction() as conn:
            result = await conn.execute(
                "delete from public.lessons where id = $1 and teacher_id = $2", lesson_id, self._teacher_id
            )
        return result == "DELETE 1"

    async def copy(self, lesson_id: UUID) -> UUID | None:
        """FR-013: new editable lesson with copies of its slides and placed activities.
        The source lesson is not modified (ACC-04)."""
        async with self._db.transaction() as conn:
            source = await conn.fetchrow(
                "select title, topic, age_group from public.lessons where id = $1 and teacher_id = $2",
                lesson_id,
                self._teacher_id,
            )
            if source is None:
                return None
            new_id = await conn.fetchval(
                "insert into public.lessons (teacher_id, title, topic, age_group, copied_from_lesson_id) "
                "values ($1, $2, $3, $4, $5) returning id",
                self._teacher_id,
                (COPY_PREFIX + source["title"])[:150],
                source["topic"],
                source["age_group"],
                lesson_id,
            )
            await conn.execute(
                """
                insert into public.activities
                  (lesson_id, teacher_id, type, title, content, approval_status, origin, approved_at, order_index)
                select $1, teacher_id, type, title, content, approval_status, origin,
                       case when approval_status = 'approved' then now() end, order_index
                from public.activities
                where lesson_id = $2 and teacher_id = $3 and order_index is not null
                """,
                new_id,
                lesson_id,
                self._teacher_id,
            )
            await conn.execute(
                """
                insert into public.slides (lesson_id, teacher_id, order_index, layout, speech, question, speech_auto)
                select $1, teacher_id, order_index, layout, speech, question, speech_auto
                from public.slides where lesson_id = $2 and teacher_id = $3
                """,
                new_id,
                lesson_id,
                self._teacher_id,
            )
        return new_id
