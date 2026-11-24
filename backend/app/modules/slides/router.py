"""Slide endpoints: the lesson deck, like PowerPoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.slides.repository import SlideRepository
from app.modules.slides.schemas import SlideCreate, SlideOrder, SlideOut, SlideUpdate
from app.modules.slides.service import SlideService

router = APIRouter(prefix="/api/v1/lessons/{lesson_id}/slides", tags=["slides"])


def get_service(db: TeacherDatabase = Depends(get_teacher_database)) -> SlideService:
    return SlideService(SlideRepository(db))


@router.get("", response_model=list[SlideOut], summary="The lesson's slides in order")
async def list_slides(lesson_id: UUID, service: SlideService = Depends(get_service)) -> list[SlideOut]:
    return await service.all(lesson_id)


@router.post("", response_model=SlideOut, status_code=status.HTTP_201_CREATED, summary="Add a slide (at the end or a position)")
async def create_slide(lesson_id: UUID, data: SlideCreate, service: SlideService = Depends(get_service)) -> SlideOut:
    return await service.create(lesson_id, data)


@router.put("/order", response_model=list[SlideOut], summary="New full order of the slides")
async def reorder_slides(lesson_id: UUID, data: SlideOrder, service: SlideService = Depends(get_service)) -> list[SlideOut]:
    return await service.reorder(lesson_id, data)


@router.patch("/{slide_id}", response_model=SlideOut, summary="Update layout, robot speech or question")
async def update_slide(
    lesson_id: UUID, slide_id: UUID, data: SlideUpdate, service: SlideService = Depends(get_service)
) -> SlideOut:
    return await service.update(lesson_id, slide_id, data)


@router.post("/{slide_id}/duplicate", response_model=SlideOut, status_code=status.HTTP_201_CREATED, summary="Duplicate a slide right after it")
async def duplicate_slide(lesson_id: UUID, slide_id: UUID, service: SlideService = Depends(get_service)) -> SlideOut:
    return await service.duplicate(lesson_id, slide_id)


@router.delete("/{slide_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a slide")
async def delete_slide(lesson_id: UUID, slide_id: UUID, service: SlideService = Depends(get_service)) -> Response:
    await service.delete(lesson_id, slide_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
