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

from app.modules.pages.layout import PageLayouts, asset_ids


def _text(max_length: int) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


Title = _text(150)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- content
# Each segment / question / step is a page; `layouts` is its visual form per mode.
class StorySegment(_Strict):
    text: _text(2000)
    question: _text(300) | None = None
    layouts: PageLayouts | None = None


class StoryContent(_Strict):
    segments: list[StorySegment] = Field(min_length=1, max_length=50)


class QaQuestion(_Strict):
    question: _text(300)
    expected_answers: list[_text(100)] = Field(default_factory=list, max_length=10)
    hint: _text(300) | None = None
    simpler_question: _text(300) | None = None
    layouts: PageLayouts | None = None


class QaContent(_Strict):
    questions: list[QaQuestion] = Field(min_length=1, max_length=30)


class InteractiveStep(_Strict):
    text: _text(500)
    layouts: PageLayouts | None = None


class InteractiveContent(_Strict):
    instructions: _text(1000)
    steps: list[InteractiveStep] = Field(min_length=1, max_length=30)


class ActivityType(StrEnum):
    story = "story"
    qa_dialogue = "qa_dialogue"
    interactive = "interactive"


PAGE_MODELS: dict[ActivityType, type[_Strict]] = {
    ActivityType.story: StorySegment,
    ActivityType.qa_dialogue: QaQuestion,
    ActivityType.interactive: InteractiveStep,
}


def content_asset_ids(content: StoryContent | QaContent | InteractiveContent) -> dict[UUID, str]:
    """Every file (id -> needed kind) referenced by the pages of an activity."""
    pages = getattr(content, "segments", None) or getattr(content, "questions", None) or content.steps
    found: dict[UUID, str] = {}
    for page in pages:
        found |= asset_ids(page.layouts)
    return found


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
