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

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

HexColor = Annotated[str, StringConstraints(pattern=re.compile(r"^#[0-9a-fA-F]{6}$"))]
ElementId = Annotated[str, StringConstraints(pattern=re.compile(r"^[A-Za-z0-9_-]{1,40}$"))]
Percent = Annotated[float, Field(ge=-50, le=150)]  # a little off-page is allowed while dragging
Size = Annotated[float, Field(gt=0, le=200)]

MAX_ELEMENTS = 30


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Box(_Strict):
    id: ElementId
    x: Percent
    y: Percent
    w: Size
    h: Size
    rotation: float = Field(default=0, ge=-360, le=360)
    z: int = Field(default=0, ge=0, le=1000)


class TextElement(_Box):
    type: Literal["text"]
    # Free text, or a binding to the page's own content (then `text` is ignored).
    text: Annotated[str, StringConstraints(max_length=500)] = ""
    binding: Literal["text", "question"] | None = None
    font_size: float = Field(default=6, gt=0, le=40)  # percent of page height
    color: HexColor = "#68546F"
    bold: bool = False
    align: Literal["start", "center", "end"] = "center"

    @model_validator(mode="after")
    def _has_text(self) -> "TextElement":
        if self.binding is None and not self.text.strip():
            raise ValueError("text element needs text or a binding")
        return self


class ImageElement(_Box):
    type: Literal["image"]
    asset_id: UUID
    fit: Literal["contain", "cover"] = "contain"
    # Worksheet mode can print images as outlines for colouring.
    outline: bool = False


class ShapeElement(_Box):
    type: Literal["shape"]
    shape: Literal["rect", "rounded", "circle", "star", "heart", "cloud"]
    fill: HexColor = "#FCDC9F"
    stroke: HexColor | None = None
    # Worksheet tracing: e.g. a dotted number to write over.
    dashed: bool = False


Element = Annotated[TextElement | ImageElement | ShapeElement, Field(discriminator="type")]


class Layout(_Strict):
    background: HexColor = "#FAEFE9"
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


def asset_ids(layouts: PageLayouts | None) -> set[UUID]:
    if layouts is None:
        return set()
    found: set[UUID] = set()
    for layout in (layouts.slide, layouts.worksheet, layouts.card):
        if layout:
            found.update(e.asset_id for e in layout.elements if isinstance(e, ImageElement))
    return found
