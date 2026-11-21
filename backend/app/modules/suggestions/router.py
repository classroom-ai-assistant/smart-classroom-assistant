"""AI suggestion endpoints, nested under a lesson (slice 3)."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Response, status

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.activities.schemas import ActivityOut, ActivityUpdate
from app.modules.ai.client import AiClient
from app.modules.ai.deps import AiRateLimiter, get_ai_client, get_ai_limiter
from app.modules.suggestions.repository import SuggestionRepository
from app.modules.suggestions.schemas import ActivityDraft, ImproveRequest, SuggestActivityRequest, SuggestLessonRequest
from app.modules.suggestions.service import SuggestionService

router = APIRouter(prefix="/api/v1/lessons/{lesson_id}/suggestions", tags=["ai suggestions"])


def get_suggestion_service(
    db: TeacherDatabase = Depends(get_teacher_database),
    limiter: AiRateLimiter = Depends(get_ai_limiter),
) -> SuggestionService:
    """For approve/reject: works even when the AI key is not configured."""
    return SuggestionService(SuggestionRepository(db), ai=None, limiter=limiter, teacher_id=db.teacher.id)


def get_ai_suggestion_service(
    db: TeacherDatabase = Depends(get_teacher_database),
    limiter: AiRateLimiter = Depends(get_ai_limiter),
    ai: AiClient = Depends(get_ai_client),
) -> SuggestionService:
    return SuggestionService(SuggestionRepository(db), ai=ai, limiter=limiter, teacher_id=db.teacher.id)


@router.post(
    "",
    response_model=ActivityOut,
    status_code=status.HTTP_201_CREATED,
    summary="AI suggests one activity of the given type (stored as proposed)",
)
async def suggest_activity(
    lesson_id: UUID,
    data: SuggestActivityRequest,
    service: SuggestionService = Depends(get_ai_suggestion_service),
) -> ActivityOut:
    return await service.suggest_activity(lesson_id, data)


@router.post(
    "/lesson",
    response_model=list[ActivityOut],
    status_code=status.HTTP_201_CREATED,
    summary="AI prepares a full lesson: story, Q&A and interactive activity (stored as proposed)",
)
async def suggest_lesson(
    lesson_id: UUID,
    data: SuggestLessonRequest = Body(default_factory=SuggestLessonRequest),
    service: SuggestionService = Depends(get_ai_suggestion_service),
) -> list[ActivityOut]:
    return await service.suggest_lesson(lesson_id, data)


@router.post(
    "/improve",
    response_model=ActivityDraft,
    summary="AI turns the teacher's draft into a structured activity (not saved)",
)
async def improve_draft(
    lesson_id: UUID,
    data: ImproveRequest,
    service: SuggestionService = Depends(get_ai_suggestion_service),
) -> ActivityDraft:
    return await service.improve(lesson_id, data)


@router.post(
    "/{suggestion_id}/approve",
    response_model=ActivityOut,
    summary="Approve a suggestion, optionally with edits; it is appended to the lesson",
)
async def approve_suggestion(
    lesson_id: UUID,
    suggestion_id: UUID,
    data: ActivityUpdate | None = Body(default=None),
    service: SuggestionService = Depends(get_suggestion_service),
) -> ActivityOut:
    return await service.approve(lesson_id, suggestion_id, data)


@router.delete("/{suggestion_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Reject (delete) a suggestion")
async def reject_suggestion(
    lesson_id: UUID, suggestion_id: UUID, service: SuggestionService = Depends(get_suggestion_service)
) -> Response:
    await service.reject(lesson_id, suggestion_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
