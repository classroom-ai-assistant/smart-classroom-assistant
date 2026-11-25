"""مكتبتي endpoints for slides."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.saved_slides.repository import SavedSlideRepository
from app.modules.saved_slides.schemas import (
    InsertSavedSlide,
    SavedSlideList,
    SavedSlideOut,
    SavedSlideRename,
    SaveSlideRequest,
)
from app.modules.saved_slides.service import SavedSlideService
from app.modules.slides.repository import SlideRepository
from app.modules.slides.schemas import SlideOut
from app.modules.slides.service import SlideService

router = APIRouter(tags=["my library (slides)"])


def get_service(db: TeacherDatabase = Depends(get_teacher_database)) -> SavedSlideService:
    return SavedSlideService(SavedSlideRepository(db), SlideService(SlideRepository(db)))


@router.get("/api/v1/saved-slides", response_model=SavedSlideList, summary="My saved slides (recently updated first)")
async def list_saved(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: SavedSlideService = Depends(get_service),
) -> SavedSlideList:
    return await service.list(limit, offset)


@router.get("/api/v1/saved-slides/{saved_id}", response_model=SavedSlideOut, summary="One saved slide")
async def get_saved(saved_id: UUID, service: SavedSlideService = Depends(get_service)) -> SavedSlideOut:
    return await service.get(saved_id)


@router.patch("/api/v1/saved-slides/{saved_id}", response_model=SavedSlideOut, summary="Rename a saved slide")
async def rename_saved(
    saved_id: UUID, data: SavedSlideRename, service: SavedSlideService = Depends(get_service)
) -> SavedSlideOut:
    return await service.rename(saved_id, data.title)


@router.delete("/api/v1/saved-slides/{saved_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove from my library")
async def delete_saved(saved_id: UUID, service: SavedSlideService = Depends(get_service)) -> Response:
    await service.delete(saved_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/v1/lessons/{lesson_id}/slides/{slide_id}/save",
    response_model=SavedSlideOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save a copy of this slide in my library",
)
async def save_slide(
    lesson_id: UUID, slide_id: UUID, data: SaveSlideRequest, service: SavedSlideService = Depends(get_service)
) -> SavedSlideOut:
    return await service.save_from_slide(lesson_id, slide_id, data.title)


@router.post(
    "/api/v1/lessons/{lesson_id}/slides/from-library",
    response_model=SlideOut,
    status_code=status.HTTP_201_CREATED,
    summary="Insert a slide from my library into this lesson",
)
async def insert_from_library(
    lesson_id: UUID, data: InsertSavedSlide, service: SavedSlideService = Depends(get_service)
) -> SlideOut:
    return await service.insert_into_lesson(lesson_id, data)
