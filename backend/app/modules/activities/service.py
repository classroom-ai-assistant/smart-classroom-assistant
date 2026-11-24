"""Activity business logic (FR-008 to FR-011, FR-021)."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.database.rls_session import TeacherDatabase
from app.modules.activities.repository import ActivityRepository
from app.modules.activities.schemas import (
    CONTENT_ADAPTERS,
    content_asset_ids,
    ActivityCreate,
    ActivityOrder,
    ActivityOut,
    ActivityType,
    ActivityUpdate,
)
from app.modules.assets.repository import missing_assets
from app.modules.lessons.service import LESSON_NOT_FOUND
from app.shared.errors.exceptions import NotFoundError, ValidationFailedError

ACTIVITY_NOT_FOUND = "النشاط غير موجود"


def validate_content(activity_type: str, content: dict[str, Any]) -> dict[str, Any]:
    """Validate `content` against the shape of `activity_type`; field errors
    are reported as content.<path>."""
    adapter = CONTENT_ADAPTERS[ActivityType(activity_type)]
    try:
        return adapter.dump_python(adapter.validate_python(content), mode="json", exclude_none=True)
    except ValidationError as exc:
        details = [
            {"field": ".".join(["content", *(str(p) for p in err["loc"])]), "type": err["type"]}
            for err in exc.errors()
        ]
        raise ValidationFailedError(details=details) from exc


async def ensure_page_assets(db: TeacherDatabase, activity_type: str, content: dict[str, Any]) -> None:
    """Every image on the pages must be one of the teacher's own files."""
    parsed = CONTENT_ADAPTERS[ActivityType(activity_type)].validate_python(content)
    if await missing_assets(db, content_asset_ids(parsed)):
        raise ValidationFailedError(
            "فيه صورة في الصفحة غير موجودة في ملفاتك", details=[{"field": "content", "type": "unknown_asset"}]
        )


class ActivityService:
    def __init__(self, repo: ActivityRepository) -> None:
        self._repo = repo

    async def create(self, lesson_id: UUID, data: ActivityCreate) -> ActivityOut:
        content = data.content.model_dump(mode="json", exclude_none=True)
        await ensure_page_assets(self._repo.db, data.type, content)
        row = await self._repo.create_manual(lesson_id, data.type, data.title, content)
        if row is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return ActivityOut(**row)

    async def update(self, lesson_id: UUID, activity_id: UUID, data: ActivityUpdate) -> ActivityOut:
        if not data.model_fields_set or all(getattr(data, f) is None for f in data.model_fields_set):
            raise ValidationFailedError(details=[{"field": "body", "type": "no_fields"}])

        content = None
        if data.content is not None:
            current = await self._repo.get(lesson_id, activity_id)
            if current is None:
                raise NotFoundError(ACTIVITY_NOT_FOUND)
            content = validate_content(current["type"], data.content)
            await ensure_page_assets(self._repo.db, current["type"], content)

        row = await self._repo.update(lesson_id, activity_id, data.title, content)
        if row is None:
            raise NotFoundError(ACTIVITY_NOT_FOUND)
        return ActivityOut(**row)

    async def delete(self, lesson_id: UUID, activity_id: UUID) -> None:
        if not await self._repo.delete(lesson_id, activity_id):
            raise NotFoundError(ACTIVITY_NOT_FOUND)

    async def reorder(self, lesson_id: UUID, data: ActivityOrder) -> list[ActivityOut]:
        try:
            rows = await self._repo.reorder(lesson_id, data.activity_ids)
        except ValueError as exc:
            raise ValidationFailedError(
                "الترتيب لازم يحتوي كل أنشطة الدرس مرة واحدة",
                details=[{"field": "activity_ids", "type": "mismatch"}],
            ) from exc
        if rows is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return [ActivityOut(**r) for r in rows]
