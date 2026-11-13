"""Business logic for the teacher's own account (FR-001 to FR-004, FR-044,
FR-086, FR-087, AUTH-09)."""

from datetime import UTC, datetime
from typing import Any

from fastapi.concurrency import run_in_threadpool

from app.core.security import CurrentTeacher
from app.modules.teachers.pin import hash_pin
from app.modules.teachers.repository import TeacherRepositoryProtocol
from app.modules.teachers.schemas import KidsModePinSet, ProfileOut, ProfileUpdate, SettingsOut, SettingsUpdate
from app.shared.errors.exceptions import NotFoundError

_PROFILE_MISSING = "لم يُعثر على ملف المعلمة. سجّلي الخروج ثم الدخول مرة أخرى"


class TeacherService:
    def __init__(self, repo: TeacherRepositoryProtocol, teacher: CurrentTeacher) -> None:
        self._repo = repo
        self._teacher = teacher

    async def get_profile(self) -> ProfileOut:
        row = await self._repo.fetch_profile(self._teacher.id)
        if row is None:
            raise NotFoundError(_PROFILE_MISSING)
        return ProfileOut(
            id=row["id"],
            email=self._teacher.email,
            display_name=row["display_name"],
            created_at=row["created_at"],
            settings=SettingsOut(
                voice_volume=row["voice_volume"],
                speech_rate=float(row["speech_rate"]),
                answer_wait_seconds=row["answer_wait_seconds"],
                no_answer_action=row["no_answer_action"],
                default_alert_lead_minutes=row["default_alert_lead_minutes"],
                has_kids_mode_pin=row["has_kids_mode_pin"],
                privacy_notice_accepted_at=row["privacy_notice_accepted_at"],
                updated_at=row["settings_updated_at"],
            ),
        )

    async def update_profile(self, data: ProfileUpdate) -> ProfileOut:
        if not await self._repo.update_display_name(self._teacher.id, data.display_name):
            raise NotFoundError(_PROFILE_MISSING)
        return await self.get_profile()

    async def update_settings(self, data: SettingsUpdate) -> ProfileOut:
        values: dict[str, Any] = {
            name: getattr(data, name) for name in data.model_fields_set if name != "privacy_notice_accepted"
        }
        if "no_answer_action" in values:
            values["no_answer_action"] = values["no_answer_action"].value
        if data.privacy_notice_accepted:
            values["privacy_notice_accepted_at"] = datetime.now(UTC)
        if values and not await self._repo.update_settings(self._teacher.id, values):
            raise NotFoundError(_PROFILE_MISSING)
        return await self.get_profile()

    async def set_kids_mode_pin(self, data: KidsModePinSet) -> ProfileOut:
        # scrypt is deliberately slow; keep it off the event loop.
        pin_hash = await run_in_threadpool(hash_pin, data.pin)
        if not await self._repo.update_settings(self._teacher.id, {"kids_mode_pin_hash": pin_hash}):
            raise NotFoundError(_PROFILE_MISSING)
        return await self.get_profile()
