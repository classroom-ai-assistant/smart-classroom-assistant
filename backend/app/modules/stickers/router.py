"""GET /api/v1/stickers: the sticker library for the editor."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import CurrentTeacher, get_current_teacher
from app.modules.stickers.catalog import CATEGORIES, CREDIT, catalog

router = APIRouter(prefix="/api/v1/stickers", tags=["stickers"])


class Sticker(BaseModel):
    name: str
    label: str
    category: str
    url: str


class StickerCatalog(BaseModel):
    items: list[Sticker]
    categories: dict[str, str]
    credit: str


@router.get("", response_model=StickerCatalog, summary="Kid-friendly sticker library (Fluent Emoji, MIT)")
async def list_stickers(_: CurrentTeacher = Depends(get_current_teacher)) -> StickerCatalog:
    return StickerCatalog(
        items=[Sticker(**{k: r[k] for k in ("name", "label", "category", "url")}) for r in catalog()],
        categories=CATEGORIES,
        credit=CREDIT,
    )
