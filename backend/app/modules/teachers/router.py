"""Endpoints for the signed-in teacher's own profile and settings.

Sign-up, login and password reset are NOT here: the browser calls
Supabase Auth for those (decision A). These endpoints need a valid token.
"""

from fastapi import APIRouter, Depends

from app.core.security import CurrentTeacher, get_current_teacher
from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.teachers.repository import TeacherRepository, TeacherRepositoryProtocol
from app.modules.teachers.schemas import KidsModePinSet, ProfileOut, ProfileUpdate, SettingsUpdate
from app.modules.teachers.service import TeacherService

router = APIRouter(prefix="/api/v1/me", tags=["teacher account"])


def get_teacher_repository(db: TeacherDatabase = Depends(get_teacher_database)) -> TeacherRepositoryProtocol:
    return TeacherRepository(db)


def get_teacher_service(
    repo: TeacherRepositoryProtocol = Depends(get_teacher_repository),
    teacher: CurrentTeacher = Depends(get_current_teacher),
) -> TeacherService:
    return TeacherService(repo, teacher)


@router.get("", response_model=ProfileOut, summary="Get my profile and settings")
async def get_me(service: TeacherService = Depends(get_teacher_service)) -> ProfileOut:
    return await service.get_profile()


@router.patch("", response_model=ProfileOut, summary="Update my display name")
async def update_me(data: ProfileUpdate, service: TeacherService = Depends(get_teacher_service)) -> ProfileOut:
    return await service.update_profile(data)


@router.patch("/settings", response_model=ProfileOut, summary="Update my assistant settings")
async def update_my_settings(
    data: SettingsUpdate, service: TeacherService = Depends(get_teacher_service)
) -> ProfileOut:
    return await service.update_settings(data)


@router.put("/kids-mode-pin", response_model=ProfileOut, summary="Set the kids-mode lock PIN")
async def set_kids_mode_pin(
    data: KidsModePinSet, service: TeacherService = Depends(get_teacher_service)
) -> ProfileOut:
    return await service.set_kids_mode_pin(data)
