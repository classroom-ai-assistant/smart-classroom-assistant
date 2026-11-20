"""Activity endpoints, nested under a lesson (FR-008 to FR-011)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.activities.repository import ActivityRepository
from app.modules.activities.schemas import ActivityCreate, ActivityOrder, ActivityOut, ActivityUpdate
from app.modules.activities.service import ActivityService

router = APIRouter(prefix="/api/v1/lessons/{lesson_id}/activities", tags=["activities"])


def get_activity_service(db: TeacherDatabase = Depends(get_teacher_database)) -> ActivityService:
    return ActivityService(ActivityRepository(db))


@router.post(
    "",
    response_model=ActivityOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a teacher-written activity (approved on save, appended last)",
)
async def create_activity(
    lesson_id: UUID, data: ActivityCreate, service: ActivityService = Depends(get_activity_service)
) -> ActivityOut:
    return await service.create(lesson_id, data)


@router.put("/order", response_model=list[ActivityOut], summary="Set the full order of the lesson's activities")
async def reorder_activities(
    lesson_id: UUID, data: ActivityOrder, service: ActivityService = Depends(get_activity_service)
) -> list[ActivityOut]:
    return await service.reorder(lesson_id, data)


@router.patch("/{activity_id}", response_model=ActivityOut, summary="Edit an activity's title or content")
async def update_activity(
    lesson_id: UUID,
    activity_id: UUID,
    data: ActivityUpdate,
    service: ActivityService = Depends(get_activity_service),
) -> ActivityOut:
    return await service.update(lesson_id, activity_id, data)


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an activity")
async def delete_activity(
    lesson_id: UUID, activity_id: UUID, service: ActivityService = Depends(get_activity_service)
) -> Response:
    await service.delete(lesson_id, activity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
