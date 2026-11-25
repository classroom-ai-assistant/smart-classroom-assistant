"""Free picture search for the slide editor (Pixabay, safe search)."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from app.core.security import CurrentTeacher, get_current_teacher
from app.modules.ai.deps import AiRateLimiter
from app.modules.images.client import ImageSearch
from app.shared.errors.exceptions import AiUnavailableError

router = APIRouter(prefix="/api/v1/images", tags=["free images"])


class ImageHit(BaseModel):
    id: int
    preview_url: str
    width: int | None
    height: int | None
    tags: str
    author: str
    page_url: str


class ImageResults(BaseModel):
    items: list[ImageHit]
    total: int
    credit: str = "Pixabay"


def get_image_search(request: Request) -> ImageSearch:
    client = getattr(request.app.state, "image_search", None)
    if client is None:
        raise AiUnavailableError("البحث عن الصور غير مفعّل حالياً")
    return client


def get_image_limiter(request: Request) -> AiRateLimiter:
    return request.app.state.image_limiter


@router.get("/search", response_model=ImageResults, summary="Search free pictures (safe for all ages)")
async def search_images(
    q: str = Query(min_length=1, max_length=80),
    page: int = Query(default=1, ge=1, le=20),
    type: Literal["all", "photo", "illustration", "vector"] = Query(default="all"),
    teacher: CurrentTeacher = Depends(get_current_teacher),
    client: ImageSearch = Depends(get_image_search),
    limiter: AiRateLimiter = Depends(get_image_limiter),
) -> ImageResults:
    limiter.check(teacher.id)
    return ImageResults(**await client.search(q.strip(), page, type))


@router.get(
    "/pixabay/{image_id}/file",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
    summary="Download a chosen picture so the browser can store it in ملفاتي",
)
async def image_file(
    image_id: int,
    teacher: CurrentTeacher = Depends(get_current_teacher),
    client: ImageSearch = Depends(get_image_search),
    limiter: AiRateLimiter = Depends(get_image_limiter),
) -> Response:
    limiter.check(teacher.id)
    content, content_type = await client.file(image_id)
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "no-store"})
