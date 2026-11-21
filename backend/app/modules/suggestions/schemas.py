"""AI suggestion shapes (slice 3)."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.modules.activities.schemas import ActivityType

Notes = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Draft = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]

MAX_PENDING_SUGGESTIONS = 20


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SuggestActivityRequest(_Strict):
    """'اقترح لي': one activity of the given type for this lesson."""

    type: ActivityType
    notes: Notes | None = None


class SuggestLessonRequest(_Strict):
    """'جهّز الدرس كامل': a story, a Q&A dialogue and an interactive activity."""

    notes: Notes | None = None


class ImproveRequest(_Strict):
    """'حسّن اللي كتبته': turn the teacher's draft into a structured activity.
    Nothing is saved; the teacher reviews the result in the form."""

    type: ActivityType
    text: Draft


class ActivityDraft(BaseModel):
    type: ActivityType
    title: str
    content: dict[str, Any]
