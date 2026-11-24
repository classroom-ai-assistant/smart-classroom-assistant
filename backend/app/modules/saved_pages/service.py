"""مكتبتي business logic: a saved page is validated exactly like a page
inside a lesson, including that its images are the teacher's own files."""

from typing import Any
from uuid import UUID

import asyncpg
from pydantic import ValidationError

from app.modules.activities.schemas import PAGE_MODELS, ActivityType
from app.modules.assets.repository import missing_assets
from app.modules.pages.layout import asset_ids
from app.modules.saved_pages.repository import SavedPageRepository
from app.modules.saved_pages.schemas import SavedPageCreate, SavedPageList, SavedPageOut, SavedPageUpdate
from app.shared.errors.exceptions import NotFoundError, ValidationFailedError

PAGE_NOT_FOUND = "الصفحة غير موجودة في مكتبتك"


class SavedPageService:
    def __init__(self, repo: SavedPageRepository) -> None:
        self._repo = repo

    async def _clean_page(self, activity_type: str, page: dict[str, Any]) -> dict[str, Any]:
        model = PAGE_MODELS[ActivityType(activity_type)]
        try:
            parsed = model.model_validate(page)
        except ValidationError as exc:
            details = [
                {"field": ".".join(["page", *(str(p) for p in err["loc"])]), "type": err["type"]} for err in exc.errors()
            ]
            raise ValidationFailedError(details=details) from exc
        if await missing_assets(self._repo.db, asset_ids(parsed.layouts)):
            raise ValidationFailedError(
                "فيه صورة في الصفحة غير موجودة في ملفاتك", details=[{"field": "page", "type": "unknown_asset"}]
            )
        return parsed.model_dump(mode="json", exclude_none=True)

    async def list(self, activity_type: str | None, limit: int, offset: int) -> SavedPageList:
        rows, total = await self._repo.list(activity_type, limit, offset)
        return SavedPageList(items=[SavedPageOut(**r) for r in rows], total=total)

    async def get(self, page_id: UUID) -> SavedPageOut:
        row = await self._repo.get(page_id)
        if row is None:
            raise NotFoundError(PAGE_NOT_FOUND)
        return SavedPageOut(**row)

    async def create(self, data: SavedPageCreate) -> SavedPageOut:
        page = await self._clean_page(data.activity_type, data.page)
        try:
            row = await self._repo.create(data.title, data.activity_type.value, page)
        except asyncpg.CheckViolationError as exc:
            raise ValidationFailedError("الصفحة كبيرة جداً", details=[{"field": "page", "type": "too_large"}]) from exc
        return SavedPageOut(**row)

    async def update(self, page_id: UUID, data: SavedPageUpdate) -> SavedPageOut:
        if data.title is None and data.page is None:
            raise ValidationFailedError(details=[{"field": "body", "type": "no_fields"}])
        page = None
        if data.page is not None:
            current = await self._repo.get(page_id)
            if current is None:
                raise NotFoundError(PAGE_NOT_FOUND)
            page = await self._clean_page(current["activity_type"], data.page)
        try:
            row = await self._repo.update(page_id, data.title, page)
        except asyncpg.CheckViolationError as exc:
            raise ValidationFailedError("الصفحة كبيرة جداً", details=[{"field": "page", "type": "too_large"}]) from exc
        if row is None:
            raise NotFoundError(PAGE_NOT_FOUND)
        return SavedPageOut(**row)

    async def delete(self, page_id: UUID) -> None:
        if not await self._repo.delete(page_id):
            raise NotFoundError(PAGE_NOT_FOUND)
