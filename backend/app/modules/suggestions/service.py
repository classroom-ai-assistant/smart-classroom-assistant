"""AI suggestions business logic (FR-016 to FR-021).

The teacher stays in control: AI output is stored as 'proposed' and never
becomes part of the lesson (or reaches children) until she approves it.
The AI call happens outside any database transaction.
"""

from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from app.modules.activities.schemas import ActivityCreate, ActivityOut, ActivityType, ActivityUpdate
from app.modules.activities.service import validate_content
from app.modules.ai import prompts
from app.modules.ai.client import AiClient, AiReplyFormatError
from app.modules.ai.deps import AiRateLimiter
from app.modules.lessons.service import LESSON_NOT_FOUND
from app.modules.suggestions.repository import SuggestionRepository
from app.modules.suggestions.schemas import (
    MAX_PENDING_SUGGESTIONS,
    ActivityDraft,
    ImproveRequest,
    SuggestActivityRequest,
    SuggestLessonRequest,
)
from app.shared.errors.exceptions import AiFailedError, AiUnavailableError, NotFoundError, ValidationFailedError

SUGGESTION_NOT_FOUND = "الاقتراح غير موجود"
TOO_MANY_PENDING = "عندك اقتراحات كثيرة بانتظار قرارك، اعتمدي أو احذفي بعضها أولاً"

_ACTIVITY = TypeAdapter(ActivityCreate)
FULL_LESSON_TYPES = [ActivityType.story, ActivityType.qa_dialogue, ActivityType.interactive]


def _as_activity(raw: Any, activity_type: ActivityType) -> dict[str, Any]:
    """Validate one AI activity; the type is ours, not the model's."""
    if not isinstance(raw, dict):
        raise ValueError("activity is not an object")
    parsed = _ACTIVITY.validate_python({"type": activity_type.value, "title": raw.get("title"), "content": raw.get("content")})
    return {
        "type": parsed.type,
        "title": parsed.title,
        "content": parsed.content.model_dump(mode="json", exclude_none=True),
    }


def _as_lesson(raw: Any) -> list[dict[str, Any]]:
    items = raw.get("activities") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("missing activities list")
    by_type = {item.get("type"): item for item in items if isinstance(item, dict)}
    return [_as_activity(by_type.get(t.value), t) for t in FULL_LESSON_TYPES]


class SuggestionService:
    def __init__(self, repo: SuggestionRepository, ai: AiClient | None, limiter: AiRateLimiter, teacher_id: UUID) -> None:
        self._repo = repo
        self._ai = ai
        self._limiter = limiter
        self._teacher_id = teacher_id

    async def _lesson(self, lesson_id: UUID, *, adding: int = 0) -> dict[str, Any]:
        lesson = await self._repo.lesson_context(lesson_id)
        if lesson is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        if adding and lesson["pending"] + adding > MAX_PENDING_SUGGESTIONS:
            raise ValidationFailedError(TOO_MANY_PENDING, details=[{"field": "suggestions", "type": "too_many"}])
        return lesson

    async def _ask(self, system: str, prompt: str, convert: Any) -> Any:
        """Ask once, and once more with a correction note if the reply does not
        fit the activity shape. Both attempts count as one teacher request."""
        if self._ai is None:
            raise AiUnavailableError()
        problem = ""
        for attempt in range(2):
            try:
                raw = await self._ai.generate_json(system, prompt + (prompts.retry_note(problem) if attempt else ""))
                return convert(raw)
            except (ValueError, ValidationError, AiReplyFormatError) as exc:
                problem = "JSON غير صالح" if isinstance(exc, AiReplyFormatError) else "حقول ناقصة أو أطول من المسموح"
        raise AiFailedError()

    async def suggest_activity(self, lesson_id: UUID, data: SuggestActivityRequest) -> ActivityOut:
        lesson = await self._lesson(lesson_id, adding=1)
        self._limiter.check(self._teacher_id)
        item = await self._ask(
            prompts.system_prompt(lesson["age_group"]),
            prompts.suggest_prompt(data.type.value, lesson["title"], lesson["topic"], data.notes),
            lambda raw: _as_activity(raw, data.type),
        )
        rows = await self._repo.insert(lesson_id, [item])
        if rows is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return ActivityOut(**rows[0])

    async def suggest_lesson(self, lesson_id: UUID, data: SuggestLessonRequest) -> list[ActivityOut]:
        lesson = await self._lesson(lesson_id, adding=len(FULL_LESSON_TYPES))
        self._limiter.check(self._teacher_id)
        items = await self._ask(
            prompts.system_prompt(lesson["age_group"]),
            prompts.full_lesson_prompt(lesson["title"], lesson["topic"], data.notes),
            _as_lesson,
        )
        rows = await self._repo.insert(lesson_id, items)
        if rows is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        return [ActivityOut(**r) for r in rows]

    async def improve(self, lesson_id: UUID, data: ImproveRequest) -> ActivityDraft:
        lesson = await self._lesson(lesson_id)
        self._limiter.check(self._teacher_id)
        item = await self._ask(
            prompts.system_prompt(lesson["age_group"]),
            prompts.improve_prompt(data.type.value, lesson["title"], lesson["topic"], data.text),
            lambda raw: _as_activity(raw, data.type),
        )
        return ActivityDraft(**item)

    async def approve(self, lesson_id: UUID, suggestion_id: UUID, data: ActivityUpdate | None) -> ActivityOut:
        title = data.title if data else None
        content = None
        if data and data.content is not None:
            current = await self._repo.get_pending(lesson_id, suggestion_id)
            if current is None:
                raise NotFoundError(SUGGESTION_NOT_FOUND)
            content = validate_content(current["type"], data.content)
        row = await self._repo.approve(lesson_id, suggestion_id, title, content)
        if row is None:
            raise NotFoundError(SUGGESTION_NOT_FOUND)
        return ActivityOut(**row)

    async def reject(self, lesson_id: UUID, suggestion_id: UUID) -> None:
        if not await self._repo.reject(lesson_id, suggestion_id):
            raise NotFoundError(SUGGESTION_NOT_FOUND)
