"""Visual page layouts (visual editor step 2, approved 2026-11-24).

Every story segment, Q&A question and interactive step is a *page*. A page
keeps its teaching content (text, question...) and may carry one layout per
mode:
- slide:     16:9, shown to the children on the robot's screen
- worksheet: A4 portrait, printed
- card:      square card, printed or shown

A missing layout is drawn from a template by the frontend, so AI or plain
text content always has a visual form.

Positions and sizes are percentages of the page (0-100), so a layout does
not depend on screen size. A text element may be *bound* to the page's own
text or question: editing the content then updates every mode.
"""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.modules.stickers.catalog import names as sticker_names

HexColor = Annotated[str, StringConstraints(pattern=re.compile(r"^#[0-9a-fA-F]{6}$"))]
ElementId = Annotated[str, StringConstraints(pattern=re.compile(r"^[A-Za-z0-9_-]{1,40}$"))]
Percent = Annotated[float, Field(ge=-50, le=150)]  # a little off-page is allowed while dragging
Size = Annotated[float, Field(gt=0, le=200)]

MAX_ELEMENTS = 40

SHAPES = (
    "rect", "rounded", "circle", "star", "heart", "cloud",
    "triangle", "diamond", "pentagon", "hexagon", "arrow", "speech_bubble",
    "sun", "moon", "flower", "line",
)
# Arabic web fonts the editor offers (loaded by the frontend from Google Fonts).
FONTS = ("tajawal", "cairo", "almarai", "changa", "amiri", "reem_kufi", "lalezar", "el_messiri")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


ANIMATIONS = ("fade", "slide_up", "slide_down", "slide_left", "slide_right", "zoom", "bounce", "pop", "spin", "wiggle")
TRANSITIONS = ("none", "fade", "slide", "zoom")


class Animation(_Strict):
    """Entrance animation, played in presentation and robot mode (not in PPTX)."""

    effect: Literal[ANIMATIONS]  # type: ignore[valid-type]
    delay: float = Field(default=0, ge=0, le=10)  # seconds after the slide appears
    duration: float = Field(default=0.6, ge=0.2, le=5)


class _Box(_Strict):
    id: ElementId
    x: Percent
    y: Percent
    w: Size
    h: Size
    rotation: float = Field(default=0, ge=-360, le=360)
    z: int = Field(default=0, ge=0, le=1000)
    opacity: float = Field(default=1, ge=0, le=1)
    # Locked elements (e.g. template decoration) cannot be moved by accident.
    locked: bool = False
    animation: Animation | None = None


class TextElement(_Box):
    type: Literal["text"]
    # Free text, or a binding to the page's own content (then `text` is ignored).
    text: Annotated[str, StringConstraints(max_length=500)] = ""
    binding: Literal["text", "question"] | None = None
    font_size: float = Field(default=6, gt=0, le=40)  # percent of page height
    color: HexColor = "#68546F"
    bold: bool = False
    underline: bool = False
    font: Literal[FONTS] = "tajawal"  # type: ignore[valid-type]
    align: Literal["start", "center", "end"] = "center"
    # Optional highlight box behind the text.
    background: HexColor | None = None

    @model_validator(mode="after")
    def _has_text(self) -> "TextElement":
        if self.binding is None and not self.text.strip():
            raise ValueError("text element needs text or a binding")
        return self


class Crop(_Strict):
    """Visible part of the image, as percentages of the original."""

    x: float = Field(ge=0, lt=100)
    y: float = Field(ge=0, lt=100)
    w: float = Field(gt=0, le=100)
    h: float = Field(gt=0, le=100)

    @model_validator(mode="after")
    def _inside(self) -> "Crop":
        if self.x + self.w > 100.001 or self.y + self.h > 100.001:
            raise ValueError("crop must stay inside the image")
        return self


class ImageElement(_Box):
    type: Literal["image"]
    asset_id: UUID
    fit: Literal["contain", "cover"] = "contain"
    # Worksheet mode can print images as outlines for colouring.
    outline: bool = False
    crop: "Crop | None" = None
    flip: bool = False  # mirror horizontally


class VideoElement(_Box):
    type: Literal["video"]
    asset_id: UUID
    autoplay: bool = False
    muted: bool = False
    loop: bool = False


class StickerElement(_Box):
    """A picture from the built-in sticker library (no upload needed)."""

    type: Literal["sticker"]
    name: str
    flip: bool = False

    @field_validator("name")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in sticker_names():
            raise ValueError("unknown sticker")
        return value


class PlaceholderElement(_Box):
    """An empty picture spot with what to look for (e.g. 'بطة صفراء').
    The teacher fills it from ملفاتي or the free image search."""

    type: Literal["placeholder"]
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class ShapeElement(_Box):
    type: Literal["shape"]
    shape: Literal[SHAPES]  # type: ignore[valid-type]
    fill: HexColor = "#FCDC9F"
    stroke: HexColor | None = None
    # Worksheet tracing: e.g. a dotted number to write over.
    dashed: bool = False


Element = Annotated[
    TextElement | ImageElement | VideoElement | StickerElement | PlaceholderElement | ShapeElement,
    Field(discriminator="type"),
]


class Layout(_Strict):
    background: HexColor = "#FAEFE9"
    # Optional picture covering the whole slide (one of the teacher's images).
    background_asset_id: UUID | None = None
    transition: Literal[TRANSITIONS] = "none"  # type: ignore[valid-type]
    elements: list[Element] = Field(default_factory=list, max_length=MAX_ELEMENTS)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Layout":
        ids = [e.id for e in self.elements]
        if len(ids) != len(set(ids)):
            raise ValueError("element ids must be unique")
        return self


class PageLayouts(_Strict):
    slide: Layout | None = None
    worksheet: Layout | None = None
    card: Layout | None = None


def layout_assets(layout: Layout | None) -> dict[UUID, str]:
    """asset id -> the file kind the element needs ('image' or 'video')."""
    if layout is None:
        return {}
    found: dict[UUID, str] = {}
    if layout.background_asset_id:
        found[layout.background_asset_id] = "image"
    for e in layout.elements:
        if isinstance(e, ImageElement):
            found[e.asset_id] = "image"
        elif isinstance(e, VideoElement):
            found[e.asset_id] = "video"
    return found


def asset_ids(layouts: PageLayouts | None) -> dict[UUID, str]:
    if layouts is None:
        return {}
    found: dict[UUID, str] = {}
    for layout in (layouts.slide, layouts.worksheet, layouts.card):
        found |= layout_assets(layout)
    return found
