"""Teacher files (visual editor step 1)."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

BUCKET = "teacher-assets"


class AssetKind(StrEnum):
    image = "image"
    pdf = "pdf"
    video = "video"


# Allowed types and size limits; must match the CHECK in migration 0007.
MIME_KIND = {
    "image/png": AssetKind.image,
    "image/jpeg": AssetKind.image,
    "image/webp": AssetKind.image,
    "image/gif": AssetKind.image,
    "application/pdf": AssetKind.pdf,
    "video/mp4": AssetKind.video,
    "video/webm": AssetKind.video,
}
MAX_BYTES = {AssetKind.image: 10 * 1024 * 1024, AssetKind.pdf: 20 * 1024 * 1024, AssetKind.video: 50 * 1024 * 1024}


class AssetRegister(BaseModel):
    """Sent by the browser after it uploaded the file to Storage itself.
    Type and size are read from Storage, not trusted from this body."""

    model_config = ConfigDict(extra="forbid")

    storage_path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
    file_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    width: int | None = Field(default=None, gt=0, le=20000)
    height: int | None = Field(default=None, gt=0, le=20000)
    # Set when the picture came from the free image search: credit its author.
    source: Literal["upload", "library"] = "upload"
    attribution: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class AssetOut(BaseModel):
    id: UUID
    kind: AssetKind
    source: str
    storage_path: str
    file_name: str
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    attribution: str | None
    created_at: datetime


class AssetList(BaseModel):
    items: list[AssetOut]
    total: int
