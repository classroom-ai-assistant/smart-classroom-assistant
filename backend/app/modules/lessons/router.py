"""Lesson endpoints (FR-005 to FR-015)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.lessons.repository import LessonRepository
from app.modules.lessons.schemas import LessonCreate, LessonDetail, LessonList, LessonUpdate
from app.modules.lessons.service import LessonService

router = APIRouter(prefix="/api/v1/lessons", tags=["lessons"])


def get_lesson_service(db: TeacherDatabase = Depends(get_teacher_database)) -> LessonService:
    return LessonService(LessonRepository(db))


@router.get("", response_model=LessonList, summary="List my lessons (newest first), optional title search")
async def list_lessons(
    q: str | None = Query(default=None, max_length=150, description="Search in lesson titles"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: LessonService = Depends(get_lesson_service),
) -> LessonList:
    return await service.list(q, limit, offset)


@router.post("", response_model=LessonDetail, status_code=status.HTTP_201_CREATED, summary="Create a lesson")
async def create_lesson(data: LessonCreate, service: LessonService = Depends(get_lesson_service)) -> LessonDetail:
    return await service.create(data)


@router.get("/{lesson_id}", response_model=LessonDetail, summary="Get a lesson with its activities")
async def get_lesson(lesson_id: UUID, service: LessonService = Depends(get_lesson_service)) -> LessonDetail:
    return await service.get(lesson_id)


@router.patch("/{lesson_id}", response_model=LessonDetail, summary="Update lesson title, topic or age group")
async def update_lesson(
    lesson_id: UUID, data: LessonUpdate, service: LessonService = Depends(get_lesson_service)
) -> LessonDetail:
    return await service.update(lesson_id, data)


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a lesson and its activities")
async def delete_lesson(lesson_id: UUID, service: LessonService = Depends(get_lesson_service)) -> Response:
    await service.delete(lesson_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{lesson_id}/copy",
    response_model=LessonDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a lesson into a new editable lesson",
)
async def copy_lesson(lesson_id: UUID, service: LessonService = Depends(get_lesson_service)) -> LessonDetail:
    return await service.copy(lesson_id)
