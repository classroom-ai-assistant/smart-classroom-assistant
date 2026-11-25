"""مكتبتي for slides (lesson editor step 2)."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SaveSlideRequest(_Strict):
    """Keep a copy of one of the lesson's slides in مكتبتي."""

    title: Title


class SavedSlideRename(_Strict):
    title: Title


class InsertSavedSlide(_Strict):
    saved_slide_id: UUID
    position: int | None = Field(default=None, ge=0)


class SavedSlideOut(BaseModel):
    id: UUID
    title: str
    layout: dict[str, Any]
    speech: str | None
    question: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class SavedSlideList(BaseModel):
    items: list[SavedSlideOut]
    total: int
