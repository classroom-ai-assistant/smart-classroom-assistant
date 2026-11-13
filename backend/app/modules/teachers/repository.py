"""SQL for the teachers module.

Every method runs inside TeacherDatabase.transaction(), so RLS limits it to
the signed-in teacher. The explicit `teacher_id = $1` filters are a second
guard on top of RLS, not the only one.
"""

from typing import Any, Protocol
from uuid import UUID

from app.database.rls_session import TeacherDatabase

# Only these columns may be updated through update_settings. Names never
# come from user input, so building the SET clause from them is safe.
UPDATABLE_SETTING_COLUMNS = frozenset(
    {
        "voice_volume",
        "speech_rate",
        "answer_wait_seconds",
        "no_answer_action",
        "default_alert_lead_minutes",
        "kids_mode_pin_hash",
        "privacy_notice_accepted_at",
    }
)

_PROFILE_SQL = """
select t.id, t.display_name, t.created_at,
       s.voice_volume, s.speech_rate, s.answer_wait_seconds,
       s.no_answer_action::text as no_answer_action,
       s.default_alert_lead_minutes,
       (s.kids_mode_pin_hash is not null) as has_kids_mode_pin,
       s.privacy_notice_accepted_at, s.updated_at as settings_updated_at
from public.teachers t
join public.teacher_settings s on s.teacher_id = t.id
where t.id = $1
"""


class TeacherRepositoryProtocol(Protocol):
    async def fetch_profile(self, teacher_id: UUID) -> dict[str, Any] | None: ...
    async def update_display_name(self, teacher_id: UUID, display_name: str) -> bool: ...
    async def update_settings(self, teacher_id: UUID, values: dict[str, Any]) -> bool: ...


class TeacherRepository:
    def __init__(self, db: TeacherDatabase) -> None:
        self._db = db

    async def fetch_profile(self, teacher_id: UUID) -> dict[str, Any] | None:
        async with self._db.transaction() as conn:
            row = await conn.fetchrow(_PROFILE_SQL, teacher_id)
        return dict(row) if row else None

    async def update_display_name(self, teacher_id: UUID, display_name: str) -> bool:
        async with self._db.transaction() as conn:
            result = await conn.execute(
                "update public.teachers set display_name = $2 where id = $1",
                teacher_id,
                display_name,
            )
        return result == "UPDATE 1"

    async def update_settings(self, teacher_id: UUID, values: dict[str, Any]) -> bool:
        unknown = set(values) - UPDATABLE_SETTING_COLUMNS
        if unknown or not values:
            raise ValueError(f"invalid settings columns: {sorted(unknown)}")

        columns = sorted(values)
        assignments = ", ".join(
            f"{column} = ${index}" + ("::public.no_answer_action" if column == "no_answer_action" else "")
            for index, column in enumerate(columns, start=2)
        )
        sql = f"update public.teacher_settings set {assignments} where teacher_id = $1"
        async with self._db.transaction() as conn:
            result = await conn.execute(sql, teacher_id, *(values[c] for c in columns))
        return result == "UPDATE 1"
