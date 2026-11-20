"""Lesson business logic (FR-005 to FR-015)."""

from uuid import UUID

from app.modules.lessons.repository import LessonRepository
from app.modules.lessons.schemas import LessonCreate, LessonDetail, LessonList, LessonSummary, LessonUpdate
from app.shared.errors.exceptions import NotFoundError

LESSON_NOT_FOUND = "الدرس غير موجود"


class LessonService:
    def __init__(self, repo: LessonRepository) -> None:
        self._repo = repo

    async def list(self, search: str | None, limit: int, offset: int) -> LessonList:
        rows, total = await self._repo.list(search.strip() if search else None, limit, offset)
        return LessonList(items=[LessonSummary(**r) for r in rows], total=total)

    async def get(self, lesson_id: UUID) -> LessonDetail:
        row = await self._repo.get(lesson_id)
        if row is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return LessonDetail(**row)

    async def create(self, data: LessonCreate) -> LessonDetail:
        lesson_id = await self._repo.create(data.title, data.topic, data.age_group.value)
        return await self.get(lesson_id)

    async def update(self, lesson_id: UUID, data: LessonUpdate) -> LessonDetail:
        values = {name: getattr(data, name) for name in data.model_fields_set}
        if "age_group" in values:
            values["age_group"] = values["age_group"].value
        if not await self._repo.update(lesson_id, values):
            raise NotFoundError(LESSON_NOT_FOUND)
        return await self.get(lesson_id)

    async def delete(self, lesson_id: UUID) -> None:
        if not await self._repo.delete(lesson_id):
            raise NotFoundError(LESSON_NOT_FOUND)

    async def copy(self, lesson_id: UUID) -> LessonDetail:
        new_id = await self._repo.copy(lesson_id)
        if new_id is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return await self.get(new_id)
