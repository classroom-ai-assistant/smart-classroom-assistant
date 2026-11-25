"""مكتبتي for slides: save a slide, list, rename, delete, insert into a lesson.

Inserting goes through SlideService.create, so the copy is validated again
(e.g. an image deleted from ملفاتي since saving is reported, not inserted)."""

from uuid import UUID

from app.modules.pages.layout import Layout
from app.modules.saved_slides.repository import SavedSlideRepository
from app.modules.saved_slides.schemas import InsertSavedSlide, SavedSlideList, SavedSlideOut
from app.modules.slides.schemas import SlideCreate, SlideOut, SlideQuestion
from app.modules.slides.service import SLIDE_NOT_FOUND, SlideService
from app.shared.errors.exceptions import NotFoundError

SAVED_NOT_FOUND = "الشريحة غير موجودة في مكتبتك"


class SavedSlideService:
    def __init__(self, repo: SavedSlideRepository, slides: SlideService) -> None:
        self._repo = repo
        self._slides = slides

    async def list(self, limit: int, offset: int) -> SavedSlideList:
        rows, total = await self._repo.page(limit, offset)
        return SavedSlideList(items=[SavedSlideOut(**r) for r in rows], total=total)

    async def get(self, saved_id: UUID) -> SavedSlideOut:
        row = await self._repo.get(saved_id)
        if row is None:
            raise NotFoundError(SAVED_NOT_FOUND)
        return SavedSlideOut(**row)

    async def save_from_slide(self, lesson_id: UUID, slide_id: UUID, title: str) -> SavedSlideOut:
        row = await self._repo.save_from_slide(lesson_id, slide_id, title)
        if row is None:
            raise NotFoundError(SLIDE_NOT_FOUND)
        return SavedSlideOut(**row)

    async def rename(self, saved_id: UUID, title: str) -> SavedSlideOut:
        row = await self._repo.rename(saved_id, title)
        if row is None:
            raise NotFoundError(SAVED_NOT_FOUND)
        return SavedSlideOut(**row)

    async def delete(self, saved_id: UUID) -> None:
        if not await self._repo.delete(saved_id):
            raise NotFoundError(SAVED_NOT_FOUND)

    async def insert_into_lesson(self, lesson_id: UUID, data: InsertSavedSlide) -> SlideOut:
        saved = await self._repo.get(data.saved_slide_id)
        if saved is None:
            raise NotFoundError(SAVED_NOT_FOUND)
        return await self._slides.create(
            lesson_id,
            SlideCreate(
                layout=Layout.model_validate(saved["layout"]),
                speech=saved["speech"],
                question=SlideQuestion.model_validate(saved["question"]) if saved["question"] else None,
                position=data.position,
            ),
        )
