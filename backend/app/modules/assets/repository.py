"""SQL for teacher files. Runs as the teacher (RLS), so storage.objects and
public.assets both only show her own rows."""

from typing import Any
from uuid import UUID

from app.database.rls_session import TeacherDatabase
from app.modules.assets.schemas import BUCKET

COLUMNS = (
    "a.id, a.kind::text as kind, a.source::text as source, a.storage_path, a.file_name, a.mime_type, "
    "a.size_bytes, a.width, a.height, a.attribution, a.created_at"
)


class AssetRepository:
    def __init__(self, db: TeacherDatabase) -> None:
        self._db = db
        self._teacher_id = db.teacher.id

    async def stored_object(self, storage_path: str) -> dict[str, Any] | None:
        """Size and type Supabase recorded for the uploaded object, if it is hers."""
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                """
                select (o.metadata ->> 'size')::bigint as size_bytes, o.metadata ->> 'mimetype' as mime_type
                from storage.objects o
                where o.bucket_id = $1 and o.name = $2
                """,
                BUCKET,
                storage_path,
            )
        return dict(row) if row else None

    async def create(self, values: dict[str, Any]) -> dict[str, Any] | None:
        """None if this file is already registered."""
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                f"""
                insert into public.assets as a
                  (teacher_id, kind, storage_path, file_name, mime_type, size_bytes, width, height)
                values ($1, $2::public.asset_kind, $3, $4, $5, $6, $7, $8)
                on conflict (storage_path) do nothing
                returning {COLUMNS}
                """,
                self._teacher_id,
                values["kind"],
                values["storage_path"],
                values["file_name"],
                values["mime_type"],
                values["size_bytes"],
                values["width"],
                values["height"],
            )
        return dict(row) if row else None

    async def list(self, kind: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        async with self._db.transaction() as conn:
            rows = await conn.fetch(
                f"""
                select {COLUMNS}, count(*) over () as total
                from public.assets a
                where a.teacher_id = $1 and ($2::public.asset_kind is null or a.kind = $2::public.asset_kind)
                order by a.created_at desc, a.id
                limit $3 offset $4
                """,
                self._teacher_id,
                kind,
                limit,
                offset,
            )
            if rows:
                total = rows[0]["total"]
            else:
                total = await conn.fetchval(
                    "select count(*) from public.assets a where a.teacher_id = $1 "
                    "and ($2::public.asset_kind is null or a.kind = $2::public.asset_kind)",
                    self._teacher_id,
                    kind,
                )
        return [{k: v for k, v in dict(r).items() if k != "total"} for r in rows], total

    async def delete(self, asset_id: UUID) -> str | None:
        """Delete the record and return its storage path (the browser then
        removes the object through the Storage API)."""
        async with self._db.transaction() as conn:
            return await conn.fetchval(
                "delete from public.assets where id = $1 and teacher_id = $2 returning storage_path",
                asset_id,
                self._teacher_id,
            )


async def missing_assets(db: TeacherDatabase, wanted: dict[UUID, str] | set[UUID]) -> set[UUID]:
    """Files a page refers to that are not this teacher's (RLS), or are the
    wrong kind (an image element pointing at a video, say)."""
    if not wanted:
        return set()
    kinds = wanted if isinstance(wanted, dict) else dict.fromkeys(wanted)
    async with db.transaction() as conn:
        rows = await conn.fetch(
            "select id, kind::text as kind from public.assets where id = any($1::uuid[])", list(kinds)
        )
    have = {r["id"]: r["kind"] for r in rows}
    return {i for i, k in kinds.items() if i not in have or (k is not None and have[i] != k)}
