"""مكتبتي: pages the teacher saves to reuse in other lessons (editor step 4)."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.modules.activities.schemas import ActivityType

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SavedPageCreate(_Strict):
    title: Title
    activity_type: ActivityType
    # One page of that type: a story segment, a question or a step, with layouts.
    page: dict[str, Any]


class SavedPageUpdate(_Strict):
    title: Title | None = None
    page: dict[str, Any] | None = None


class SavedPageOut(BaseModel):
    id: UUID
    title: str
    activity_type: ActivityType
    page: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SavedPageList(BaseModel):
    items: list[SavedPageOut]
    total: int
