"""Slides business logic: validation, own-files check, deck limits."""

from typing import Any
from uuid import UUID

import asyncpg

from app.modules.assets.repository import missing_assets
from app.modules.lessons.service import LESSON_NOT_FOUND
from app.modules.pages.layout import Layout, layout_assets
from app.modules.slides.repository import SlideRepository
from app.modules.slides.schemas import MAX_SLIDES, SlideCreate, SlideOrder, SlideOut, SlideUpdate
from app.shared.errors.exceptions import NotFoundError, ValidationFailedError

SLIDE_NOT_FOUND = "الشريحة غير موجودة"


class SlideService:
    def __init__(self, repo: SlideRepository) -> None:
        self._repo = repo

    async def _check_files(self, layout: Layout) -> None:
        if await missing_assets(self._repo.db, layout_assets(layout)):
            raise ValidationFailedError(
                "فيه صورة أو مقطع في الشريحة غير موجود في ملفاتك",
                details=[{"field": "layout", "type": "unknown_asset"}],
            )

    @staticmethod
    def _too_large(exc: Exception) -> ValidationFailedError:
        return ValidationFailedError("الشريحة كبيرة جداً", details=[{"field": "layout", "type": "too_large"}])

    async def all(self, lesson_id: UUID) -> list[SlideOut]:
        rows = await self._repo.all(lesson_id)
        if rows is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return [SlideOut(**r) for r in rows]

    async def create(self, lesson_id: UUID, data: SlideCreate) -> SlideOut:
        if await self._repo.count(lesson_id) >= MAX_SLIDES:
            raise ValidationFailedError(
                f"الحد الأقصى {MAX_SLIDES} شريحة في الدرس", details=[{"field": "slides", "type": "too_many"}]
            )
        await self._check_files(data.layout)
        try:
            row = await self._repo.insert(
                lesson_id,
                data.position,
                data.layout.model_dump(mode="json"),
                data.speech or None,
                data.question.model_dump(mode="json", exclude_none=True) if data.question else None,
            )
        except asyncpg.CheckViolationError as exc:
            raise self._too_large(exc) from exc
        if row is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return SlideOut(**row)

    async def duplicate(self, lesson_id: UUID, slide_id: UUID) -> SlideOut:
        source = await self._repo.get(lesson_id, slide_id)
        if source is None:
            raise NotFoundError(SLIDE_NOT_FOUND)
        if await self._repo.count(lesson_id) >= MAX_SLIDES:
            raise ValidationFailedError(
                f"الحد الأقصى {MAX_SLIDES} شريحة في الدرس", details=[{"field": "slides", "type": "too_many"}]
            )
        row = await self._repo.insert(
            lesson_id, source["order_index"] + 1, source["layout"], source["speech"], source["question"]
        )
        if row is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return SlideOut(**row)

    async def update(self, lesson_id: UUID, slide_id: UUID, data: SlideUpdate) -> SlideOut:
        fields = data.model_fields_set
        if not fields:
            raise ValidationFailedError(details=[{"field": "body", "type": "no_fields"}])
        if "layout" in fields and data.layout is None:
            raise ValidationFailedError(details=[{"field": "layout", "type": "null_not_allowed"}])
        values: dict[str, Any] = {}
        if data.layout is not None:
            await self._check_files(data.layout)
            values["layout"] = data.layout.model_dump(mode="json")
        if "speech" in fields:
            values["speech"] = data.speech or None
        if "question" in fields:
            values["question"] = data.question.model_dump(mode="json", exclude_none=True) if data.question else None
        try:
            row = await self._repo.update(lesson_id, slide_id, values)
        except asyncpg.CheckViolationError as exc:
            raise self._too_large(exc) from exc
        if row is None:
            raise NotFoundError(SLIDE_NOT_FOUND)
        return SlideOut(**row)

    async def delete(self, lesson_id: UUID, slide_id: UUID) -> None:
        if not await self._repo.delete(lesson_id, slide_id):
            raise NotFoundError(SLIDE_NOT_FOUND)

    async def reorder(self, lesson_id: UUID, data: SlideOrder) -> list[SlideOut]:
        try:
            rows = await self._repo.reorder(lesson_id, data.slide_ids)
        except ValueError as exc:
            raise ValidationFailedError(
                "الترتيب لازم يحتوي كل شرائح الدرس مرة واحدة", details=[{"field": "slide_ids", "type": "mismatch"}]
            ) from exc
        if rows is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return [SlideOut(**r) for r in rows]
