"""SQL for مكتبتي (RLS: own rows only)."""

from typing import Any
from uuid import UUID

from app.database.rls_session import TeacherDatabase

COLUMNS = "id, title, activity_type::text as activity_type, page, created_at, updated_at"


class SavedPageRepository:
    def __init__(self, db: TeacherDatabase) -> None:
        self._db = db
        self._teacher_id = db.teacher.id

    @property
    def db(self) -> TeacherDatabase:
        return self._db

    async def list(self, activity_type: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        where = "teacher_id = $1 and ($2::public.activity_type is null or activity_type = $2::public.activity_type)"
        async with self._db.transaction() as conn:
            rows = await conn.fetch(
                f"select {COLUMNS} from public.saved_pages where {where} "
                "order by updated_at desc, id limit $3 offset $4",
                self._teacher_id,
                activity_type,
                limit,
                offset,
            )
            total = await conn.fetchval(
                f"select count(*) from public.saved_pages where {where}", self._teacher_id, activity_type
            )
        return [dict(r) for r in rows], total

    async def get(self, page_id: UUID) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"select {COLUMNS} from public.saved_pages where id = $1 and teacher_id = $2", page_id, self._teacher_id
            )
        return dict(row) if row else None

    async def create(self, title: str, activity_type: str, page: dict[str, Any]) -> dict[str, Any]:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"insert into public.saved_pages (teacher_id, title, activity_type, page) "
                f"values ($1, $2, $3::public.activity_type, $4) returning {COLUMNS}",
                self._teacher_id,
                title,
                activity_type,
                page,
            )
        return dict(row)

    async def update(self, page_id: UUID, title: str | None, page: dict[str, Any] | None) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"update public.saved_pages set title = coalesce($3, title), page = coalesce($4::jsonb, page) "
                f"where id = $1 and teacher_id = $2 returning {COLUMNS}",
                page_id,
                self._teacher_id,
                title,
                page,
            )
        return dict(row) if row else None

    async def delete(self, page_id: UUID) -> bool:
        async with self._db.transaction() as conn:
            deleted = await conn.fetchval(
                "delete from public.saved_pages where id = $1 and teacher_id = $2 returning id", page_id, self._teacher_id
            )
        return deleted is not None
