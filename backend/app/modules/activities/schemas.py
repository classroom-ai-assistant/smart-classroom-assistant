"""Activity shapes (FR-008, FR-030, UC-07).

`content` is stored as jsonb; its shape depends on the activity type and is
enforced here. The robot reads these structures during a session:
- story: ordered segments; a segment may end with a question (FR-026/FR-027)
- qa_dialogue: questions with expected answers, a hint and a simpler wording (FR-038/FR-040)
- interactive: instructions and ordered steps (FR-030)
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter


def _text(max_length: int) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


Title = _text(150)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- content
class StorySegment(_Strict):
    text: _text(2000)
    question: _text(300) | None = None


class StoryContent(_Strict):
    segments: list[StorySegment] = Field(min_length=1, max_length=50)


class QaQuestion(_Strict):
    question: _text(300)
    expected_answers: list[_text(100)] = Field(default_factory=list, max_length=10)
    hint: _text(300) | None = None
    simpler_question: _text(300) | None = None


class QaContent(_Strict):
    questions: list[QaQuestion] = Field(min_length=1, max_length=30)


class InteractiveStep(_Strict):
    text: _text(500)


class InteractiveContent(_Strict):
    instructions: _text(1000)
    steps: list[InteractiveStep] = Field(min_length=1, max_length=30)


class ActivityType(StrEnum):
    story = "story"
    qa_dialogue = "qa_dialogue"
    interactive = "interactive"


CONTENT_ADAPTERS: dict[ActivityType, TypeAdapter[Any]] = {
    ActivityType.story: TypeAdapter(StoryContent),
    ActivityType.qa_dialogue: TypeAdapter(QaContent),
    ActivityType.interactive: TypeAdapter(InteractiveContent),
}


# ---------------------------------------------------------------- requests
class _CreateBase(_Strict):
    title: Title


class StoryCreate(_CreateBase):
    type: Literal["story"]
    content: StoryContent


class QaCreate(_CreateBase):
    type: Literal["qa_dialogue"]
    content: QaContent


class InteractiveCreate(_CreateBase):
    type: Literal["interactive"]
    content: InteractiveContent


ActivityCreate = Annotated[StoryCreate | QaCreate | InteractiveCreate, Field(discriminator="type")]


class ActivityUpdate(_Strict):
    """Partial update. `content` is validated against the activity's existing type."""

    title: Title | None = None
    content: dict[str, Any] | None = None


class ActivityOrder(_Strict):
    """FR-009: the full new order of the lesson's activities."""

    activity_ids: list[UUID] = Field(min_length=1, max_length=200)


# ---------------------------------------------------------------- responses
class ActivityOut(BaseModel):
    id: UUID
    lesson_id: UUID
    type: ActivityType
    title: str
    content: dict[str, Any]
    approval_status: Literal["proposed", "approved", "rejected"]
    origin: Literal["manual", "ai"]
    order_index: int | None
    created_at: datetime
    updated_at: datetime
