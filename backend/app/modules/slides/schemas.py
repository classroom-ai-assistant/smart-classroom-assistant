"""Slides: the lesson as a deck (approved 2026-11-24).

A slide = its visual layout (same Layout as page layouts, incl. video),
`speech` = what the robot says on this slide (like speaker notes), and an
optional `question` for the children."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.activities.schemas import QaQuestion
from app.modules.pages.layout import Layout

Speech = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
MAX_SLIDES = 100


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlideQuestion(QaQuestion):
    """Same shape as a Q&A question, without page layouts."""

    layouts: None = None


class SlideCreate(_Strict):
    layout: Layout = Field(default_factory=Layout)
    speech: Speech | None = None
    question: SlideQuestion | None = None
    # 0-based place in the deck; omitted = at the end.
    position: int | None = Field(default=None, ge=0)


class SlideUpdate(_Strict):
    """Partial update. Send `speech` or `question` as null to clear it."""

    layout: Layout | None = None
    speech: Speech | None = None
    question: SlideQuestion | None = None


class SlideOrder(_Strict):
    slide_ids: list[UUID] = Field(min_length=1, max_length=MAX_SLIDES)


class SlideOut(BaseModel):
    id: UUID
    lesson_id: UUID
    order_index: int
    layout: dict[str, Any]
    speech: str | None
    # True when the robot wrote `speech` itself (it may rewrite it later);
    # False when the teacher wrote it (kept as she wrote it).
    speech_auto: bool
    question: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
