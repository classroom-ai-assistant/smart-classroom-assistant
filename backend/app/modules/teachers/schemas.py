"""Request and response shapes for the teacher's own profile and settings.

Ranges mirror the CHECK constraints in the database so bad input is
rejected here with a clear field name, before it reaches the database.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class NoAnswerAction(StrEnum):
    repeat = "repeat"
    encourage = "encourage"
    skip = "skip"


DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SettingsOut(BaseModel):
    voice_volume: int
    speech_rate: float
    answer_wait_seconds: int
    no_answer_action: NoAnswerAction
    default_alert_lead_minutes: int
    has_kids_mode_pin: bool
    privacy_notice_accepted_at: datetime | None
    updated_at: datetime


class ProfileOut(BaseModel):
    id: UUID
    email: str | None
    display_name: str
    created_at: datetime
    settings: SettingsOut


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName


class SettingsUpdate(BaseModel):
    """Partial update: send only the fields that change."""

    model_config = ConfigDict(extra="forbid")

    voice_volume: int | None = Field(default=None, ge=0, le=100)
    speech_rate: float | None = Field(default=None, ge=0.5, le=1.5)
    answer_wait_seconds: int | None = Field(default=None, ge=3, le=30)
    no_answer_action: NoAnswerAction | None = None
    default_alert_lead_minutes: int | None = Field(default=None, ge=0, le=60)
    # FR-086: the teacher acknowledges the external-processing notice. Can only be set, not undone.
    privacy_notice_accepted: Annotated[bool, Field(strict=True)] | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "SettingsUpdate":
        if not self.model_fields_set:
            raise ValueError("no fields to update")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if self.privacy_notice_accepted is False:
            raise ValueError("privacy_notice_accepted can only be true")
        return self


class KidsModePinSet(BaseModel):
    """AUTH-09: PIN that locks the children's display. Stored hashed only."""

    model_config = ConfigDict(extra="forbid")

    pin: Annotated[str, StringConstraints(pattern=r"^[0-9]{4,6}$")]
