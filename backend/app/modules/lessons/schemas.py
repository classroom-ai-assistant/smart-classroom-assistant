"""Lesson request/response shapes (FR-005 to FR-015). Ranges mirror the DB CHECKs."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.modules.activities.schemas import ActivityOut

LessonTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
LessonTopic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class AgeGroup(StrEnum):
    age_3_4 = "age_3_4"
    age_4_5 = "age_4_5"
    age_5_6 = "age_5_6"
    mixed_3_6 = "mixed_3_6"


class LessonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: LessonTitle
    topic: LessonTopic
    age_group: AgeGroup


class LessonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: LessonTitle | None = None
    topic: LessonTopic | None = None
    age_group: AgeGroup | None = None

    @model_validator(mode="after")
    def _non_empty(self) -> "LessonUpdate":
        if not self.model_fields_set:
            raise ValueError("no fields to update")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class LessonSummary(BaseModel):
    id: UUID
    title: str
    topic: str
    age_group: AgeGroup
    status: Literal["draft", "ready"]  # derived, never stored (FR-015, BRL-12)
    activity_count: int
    copied_from_lesson_id: UUID | None
    created_at: datetime
    updated_at: datetime


class LessonDetail(LessonSummary):
    activities: list[ActivityOut]


class LessonList(BaseModel):
    items: list[LessonSummary]
    total: int
