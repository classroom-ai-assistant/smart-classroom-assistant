"""AI-designed slides (lesson step 3).

The teacher stays in control: generation and assist return *drafts* only;
nothing is saved until the editor adds them through the normal slide API
(which validates again). Only lesson title/topic/age, the teacher's notes
and the slide's own text are sent to the model.
"""

import logging
import re
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.ai import prompts
from app.modules.ai.client import AiClient, AiReplyFormatError
from app.modules.ai.deps import AiRateLimiter, get_ai_client, get_ai_limiter
from app.modules.lessons.service import LESSON_NOT_FOUND
from app.modules.pages.layout import ANIMATIONS, FONTS, MAX_ELEMENTS, SHAPES, TRANSITIONS, Layout
from app.modules.slides import design_prompts
from app.modules.slides.schemas import SlideQuestion, Speech
from app.modules.stickers.catalog import names as sticker_names
from app.shared.errors.exceptions import AiFailedError, NotFoundError

logger = logging.getLogger("app.ai")

router = APIRouter(prefix="/api/v1/lessons/{lesson_id}/slides", tags=["slides (AI)"])

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
Notes = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateRequest(_Strict):
    template: Literal["letter", "number", "story", "thing", "morning", "free"] = "free"
    notes: Notes | None = None
    count: int = Field(default=5, ge=3, le=8)


class SlideDraft(_Strict):
    layout: Layout
    speech: Speech | None = None
    question: SlideQuestion | None = None


class GenerateResult(BaseModel):
    slides: list[SlideDraft]
    requested: int


class AssistRequest(_Strict):
    action: Literal["speech", "question", "simplify"]
    layout: Layout
    speech: Speech | None = None


class AssistResult(BaseModel):
    speech: str | None = None
    question: SlideQuestion | None = None
    layout: Layout | None = None


# ----------------------------------------------------------------- cleaning
def _num(value: Any, low: float, high: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, v))


def _clean_element(raw: Any, index: int, used: set[str]) -> dict[str, Any] | None:
    """Make a model-written element fit the schema, or drop it."""
    if not isinstance(raw, dict) or raw.get("type") not in {"text", "shape", "sticker", "placeholder"}:
        return None
    el: dict[str, Any] = {"type": raw["type"]}
    el_id = str(raw.get("id") or "")
    if not _ID.match(el_id) or el_id in used:
        el_id = f"ai{index}"
    used.add(el_id)
    el["id"] = el_id
    el["x"] = _num(raw.get("x"), 0, 95, 10)
    el["y"] = _num(raw.get("y"), 0, 95, 10)
    el["w"] = _num(raw.get("w"), 2, 100 - el["x"], 20)
    el["h"] = _num(raw.get("h"), 2, 100 - el["y"], 20)
    el["rotation"] = _num(raw.get("rotation"), -45, 45, 0)
    el["z"] = int(_num(raw.get("z"), 0, 1000, index))
    anim = raw.get("animation")
    if isinstance(anim, dict) and anim.get("effect") in ANIMATIONS:
        el["animation"] = {
            "effect": anim["effect"],
            "delay": _num(anim.get("delay"), 0, 10, 0),
            "duration": _num(anim.get("duration"), 0.2, 5, 0.6),
        }
    kind = raw["type"]
    if kind == "text":
        text = str(raw.get("text") or "").strip()[:500]
        if not text:
            return None
        el.update(
            text=text,
            font=raw.get("font") if raw.get("font") in FONTS else "tajawal",
            font_size=_num(raw.get("font_size"), 3, 20, 7),
            bold=bool(raw.get("bold", False)),
            align=raw.get("align") if raw.get("align") in ("start", "center", "end") else "center",
        )
        if isinstance(raw.get("color"), str) and _HEX.match(raw["color"]):
            el["color"] = raw["color"]
    elif kind == "shape":
        el["shape"] = raw.get("shape") if raw.get("shape") in SHAPES else "rounded"
        if isinstance(raw.get("fill"), str) and _HEX.match(raw["fill"]):
            el["fill"] = raw["fill"]
        el["dashed"] = bool(raw.get("dashed", False))
    elif kind == "sticker":
        if raw.get("name") not in sticker_names():
            return None
        el["name"] = raw["name"]
    else:
        query = str(raw.get("query") or "").strip()[:80]
        if not query:
            return None
        el["query"] = query
    return el


def clean_slide(raw: Any) -> SlideDraft | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("layout"), dict):
        return None
    layout_raw = raw["layout"]
    used: set[str] = set()
    elements = [
        e for i, r in enumerate((layout_raw.get("elements") or [])[:MAX_ELEMENTS])
        if (e := _clean_element(r, i, used))
    ]
    if not elements:
        return None
    layout: dict[str, Any] = {
        "elements": elements,
        "transition": layout_raw.get("transition") if layout_raw.get("transition") in TRANSITIONS else "fade",
    }
    if isinstance(layout_raw.get("background"), str) and _HEX.match(layout_raw["background"]):
        layout["background"] = layout_raw["background"]
    speech = raw.get("speech")
    speech = str(speech).strip()[:2000] if speech else None
    question = None
    if isinstance(raw.get("question"), dict):
        try:
            question = SlideQuestion.model_validate(
                {k: v for k, v in raw["question"].items() if k in {"question", "expected_answers", "hint", "simpler_question"}}
            )
        except ValidationError:
            question = None
    try:
        return SlideDraft(layout=Layout.model_validate(layout), speech=speech or None, question=question)
    except ValidationError:
        return None


# ----------------------------------------------------------------- service
async def _lesson(db: TeacherDatabase, lesson_id: UUID) -> dict[str, Any]:
    async with db.transaction() as conn:
        row = await conn.fetchrow(
            "select title, topic, age_group::text as age_group from public.lessons where id = $1 and teacher_id = $2",
            lesson_id,
            db.teacher.id,
        )
    if row is None:
        raise NotFoundError(LESSON_NOT_FOUND)
    return dict(row)


def _system(age_group: str) -> str:
    return prompts.system_prompt(age_group) + design_prompts.design_rules()


@router.post("/generate", response_model=GenerateResult, summary="AI designs slides (draft only, not saved)")
async def generate_slides(
    lesson_id: UUID,
    data: GenerateRequest,
    db: TeacherDatabase = Depends(get_teacher_database),
    ai: AiClient = Depends(get_ai_client),
    limiter: AiRateLimiter = Depends(get_ai_limiter),
) -> GenerateResult:
    lesson = await _lesson(db, lesson_id)
    limiter.check(db.teacher.id)
    prompt = design_prompts.generate_prompt(lesson["title"], lesson["topic"], data.template, data.count, data.notes)
    for attempt in range(2):
        try:
            raw = await ai.generate_json(_system(lesson["age_group"]), prompt + (prompts.retry_note("لا توجد شرائح صالحة") if attempt else ""))
        except AiReplyFormatError:
            continue
        items = raw.get("slides") if isinstance(raw, dict) else None
        drafts = [d for r in (items or [])[: data.count] if (d := clean_slide(r))]
        if drafts:
            if len(drafts) < len(items or []):
                logger.info("ai design kept %s of %s slides", len(drafts), len(items or []))
            return GenerateResult(slides=drafts, requested=data.count)
    raise AiFailedError()


def _slide_text(layout: Layout) -> str:
    return "\n".join(f"[{e.id}] {e.text}" for e in layout.elements if getattr(e, "type", "") == "text" and e.text)


@router.post("/assist", response_model=AssistResult, summary="AI helps on one slide (draft only, not saved)")
async def assist_slide(
    lesson_id: UUID,
    data: AssistRequest,
    db: TeacherDatabase = Depends(get_teacher_database),
    ai: AiClient = Depends(get_ai_client),
    limiter: AiRateLimiter = Depends(get_ai_limiter),
) -> AssistResult:
    lesson = await _lesson(db, lesson_id)
    limiter.check(db.teacher.id)
    text = _slide_text(data.layout) or "(لا يوجد نص في الشريحة)"
    prompt = design_prompts.assist_prompt(data.action, text, data.speech, lesson["title"], lesson["topic"])
    for _ in range(2):
        try:
            raw = await ai.generate_json(prompts.system_prompt(lesson["age_group"]), prompt)
        except AiReplyFormatError:
            continue
        if not isinstance(raw, dict):
            continue
        try:
            if data.action == "speech" and str(raw.get("speech") or "").strip():
                return AssistResult(speech=str(raw["speech"]).strip()[:2000])
            if data.action == "question" and isinstance(raw.get("question"), dict):
                return AssistResult(question=SlideQuestion.model_validate(raw["question"]))
            if data.action == "simplify" and isinstance(raw.get("texts"), dict):
                texts = {k: str(v).strip()[:500] for k, v in raw["texts"].items() if str(v).strip()}
                elements = [
                    e.model_copy(update={"text": texts[e.id]}) if e.type == "text" and e.id in texts and not e.binding else e
                    for e in data.layout.elements
                ]
                return AssistResult(layout=data.layout.model_copy(update={"elements": elements}))
        except ValidationError:
            continue
    raise AiFailedError()
