"""مكتبتي endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.activities.schemas import ActivityType
from app.modules.saved_pages.repository import SavedPageRepository
from app.modules.saved_pages.schemas import SavedPageCreate, SavedPageList, SavedPageOut, SavedPageUpdate
from app.modules.saved_pages.service import SavedPageService

router = APIRouter(prefix="/api/v1/saved-pages", tags=["my library"])


def get_service(db: TeacherDatabase = Depends(get_teacher_database)) -> SavedPageService:
    return SavedPageService(SavedPageRepository(db))


@router.get("", response_model=SavedPageList, summary="List my saved pages (recently updated first)")
async def list_pages(
    activity_type: ActivityType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: SavedPageService = Depends(get_service),
) -> SavedPageList:
    return await service.list(activity_type.value if activity_type else None, limit, offset)


@router.post("", response_model=SavedPageOut, status_code=status.HTTP_201_CREATED, summary="Save a page to my library")
async def create_page(data: SavedPageCreate, service: SavedPageService = Depends(get_service)) -> SavedPageOut:
    return await service.create(data)


@router.get("/{page_id}", response_model=SavedPageOut, summary="Get a saved page")
async def get_page(page_id: UUID, service: SavedPageService = Depends(get_service)) -> SavedPageOut:
    return await service.get(page_id)


@router.patch("/{page_id}", response_model=SavedPageOut, summary="Rename or replace a saved page")
async def update_page(
    page_id: UUID, data: SavedPageUpdate, service: SavedPageService = Depends(get_service)
) -> SavedPageOut:
    return await service.update(page_id, data)


@router.delete("/{page_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a saved page")
async def delete_page(page_id: UUID, service: SavedPageService = Depends(get_service)) -> Response:
    await service.delete(page_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
