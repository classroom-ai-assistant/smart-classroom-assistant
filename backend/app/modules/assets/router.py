"""Teacher files (visual editor step 1).

The browser uploads to the private `teacher-assets` bucket with the
teacher's own session, then registers the file here. Type and size are
taken from what Storage recorded, never from the request.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.assets.repository import AssetRepository
from app.modules.assets.schemas import AssetKind, AssetList, AssetOut, AssetRegister
from app.modules.assets.service import AssetService

router = APIRouter(prefix="/api/v1/assets", tags=["teacher files"])


class AssetDeleted(BaseModel):
    """Path of the removed record; the browser deletes the object from Storage."""

    storage_path: str


def get_asset_service(db: TeacherDatabase = Depends(get_teacher_database)) -> AssetService:
    return AssetService(AssetRepository(db), db.teacher.id)


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED, summary="Register an uploaded file")
async def register_asset(data: AssetRegister, service: AssetService = Depends(get_asset_service)) -> AssetOut:
    return await service.register(data)


@router.get("", response_model=AssetList, summary="List my files (newest first)")
async def list_assets(
    kind: AssetKind | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: AssetService = Depends(get_asset_service),
) -> AssetList:
    return await service.list(kind.value if kind else None, limit, offset)


@router.delete("/{asset_id}", response_model=AssetDeleted, summary="Delete a file record")
async def delete_asset(asset_id: UUID, service: AssetService = Depends(get_asset_service)) -> AssetDeleted:
    return AssetDeleted(storage_path=await service.delete(asset_id))
