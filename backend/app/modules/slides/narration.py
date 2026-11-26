"""The robot writes its own words for the whole deck (approved 2026-11-26).

One AI call sees every slide in order (texts, sticker names, picture spots,
questions), so the words flow from slide to slide in the robot's own
character: it greets the children and says its name on the first slide,
links the slides together, adds small safe classroom interactions, and
closes with encouragement on the last one.

The teacher stays in control:
- words she wrote herself (speech_auto = false) are kept and only shown to
  the model as context, unless she asks to rewrite everything;
- she can edit any slide's words afterwards, which marks them as hers.

Only the lesson, the slides and the teacher's robot settings are sent to
the model. Nothing about any child is.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.ai import prompts
from app.modules.ai.client import AiClient, AiReplyFormatError
from app.modules.ai.deps import AiRateLimiter, get_ai_client, get_ai_limiter
from app.modules.lessons.service import LESSON_NOT_FOUND
from app.modules.slides.repository import SlideRepository
from app.modules.slides.schemas import SlideOut
from app.modules.stickers.catalog import catalog
from app.shared.errors.exceptions import AiFailedError, NotFoundError, ValidationFailedError

logger = logging.getLogger("app.ai")

router = APIRouter(prefix="/api/v1/lessons/{lesson_id}", tags=["slides (AI)"])

MAX_NARRATED_SLIDES = 40
MAX_SPEECH = 2000

STYLES = {
    "storyteller": "حكواتي دافئ: يحكي كل شيء كأنه قصة، يستخدم «كان يا ما كان» و«وفجأة» ويشوّق الأطفال لما بعده.",
    "playful": "مرح ونشيط: متحمّس، يحب الألعاب الصغيرة والتصفيق، ويمدح الأطفال كثيراً بكلمات قصيرة.",
    "calm": "هادئ ولطيف: يتكلم ببطء وبجمل قصيرة جداً، صبور ومطمئن، ويناسب الأطفال الأصغر سناً.",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NarrateRequest(_Strict):
    # False (default): write only slides with no words or words the robot wrote.
    # True: rewrite every slide, including words the teacher wrote herself.
    rewrite_all: bool = False


class NarrateResult(BaseModel):
    slides: list[SlideOut]
    written: int  # slides whose words the robot wrote now
    kept: int  # slides whose words the teacher wrote and were left as they are


# ----------------------------------------------------------------- prompt
def _sticker_labels() -> dict[str, str]:
    return {s["name"]: s["label"] for s in catalog()}


def describe_slide(slide: dict[str, Any], labels: dict[str, str]) -> str:
    """What the children see on a slide, in plain words for the model."""
    parts: list[str] = []
    question = slide.get("question") or {}
    for e in (slide.get("layout") or {}).get("elements", []):
        kind = e.get("type")
        if kind == "text":
            text = question.get("question") if e.get("binding") == "question" else e.get("text")
            if text and str(text).strip():
                parts.append(f"نص: {str(text).strip()}")
        elif kind == "sticker" and e.get("name") in labels:
            parts.append(f"صورة: {labels[e['name']]}")
        elif kind == "placeholder" and e.get("query"):
            parts.append(f"صورة: {e['query']}")
        elif kind == "image":
            parts.append("صورة من ملفات المعلمة")
        elif kind == "video":
            parts.append("مقطع فيديو")
    if question.get("question"):
        parts.append(f"سؤال للأطفال: {question['question']}")
    return "، ".join(parts) or "(شريحة بلا نص)"


def narrate_prompt(
    lesson: dict[str, Any], robot_name: str, robot_style: str, slides: list[dict[str, Any]], targets: set[int]
) -> str:
    labels = _sticker_labels()
    lines = []
    for i, s in enumerate(slides, start=1):
        line = f"شريحة {i}: <<<{describe_slide(s, labels)}>>>"
        if i - 1 not in targets and s.get("speech"):
            line += f"\n  (كلام المعلمة لهذه الشريحة، لا تغيّره واجعل كلامك يتصل به: <<<{s['speech']}>>>)"
        lines.append(line)
    wanted = ", ".join(str(i + 1) for i in sorted(targets))
    return (
        f"عنوان الدرس: {lesson['title']}\nموضوع الدرس: {lesson['topic']}\n"
        f"أنت الروبوت الذي يقدّم الدرس للأطفال، واسمك: <<<{robot_name}>>>.\n"
        f"شخصيتك: {STYLES.get(robot_style, STYLES['playful'])}\n"
        f"الدرس {len(slides)} شرائح بهذا الترتيب:\n" + "\n".join(lines) + "\n"
        f"اكتب كلامك أنت للشرائح رقم: {wanted}.\n"
        "قواعد الكلام:\n"
        "- في الشريحة الأولى سلّم على الأطفال وعرّفهم باسمك ثم قدّم موضوع الدرس بتشويق.\n"
        "- في الشريحة الأخيرة اختم بتلخيص بسيط جداً وتشجيع ومديح للأطفال.\n"
        "- اربط كل شريحة بالتي قبلها (مثل: «والآن...»، «هل تعرفون ماذا بعد؟») حتى يكون الكلام قصة واحدة متصلة.\n"
        "- تكلّم عمّا يظهر في الشريحة نفسها، ولا تذكر أشياء غير موجودة فيها.\n"
        "- من جملتين إلى أربع جمل قصيرة لكل شريحة (حتى 400 حرف تقريباً).\n"
        "- أضف أحياناً تفاعلاً صغيراً آمناً داخل الفصل: «صفّقوا معي»، «قولوا معي»، «أشيروا إلى...»، «ارفعوا أيديكم»، «هيا نعدّ معاً».\n"
        "- إذا كان في الشريحة سؤال للأطفال فاختم كلامك بطرح السؤال نفسه.\n"
        "- خاطب الأطفال جميعاً (يا أصدقائي، يا أبطال)، ولا تنادِ طفلاً باسمه ولا تسأل عن أي معلومة شخصية.\n"
        "- لا تكتب علامات أو رموز تعبيرية أو وصفاً للحركة بين أقواس؛ فقط الكلام الذي يُقال بصوت عالٍ.\n"
        'أجب بالشكل: {"slides": [{"n": رقم الشريحة, "speech": "كلامك"}]}'
    )


def pick_speeches(raw: Any, targets: set[int]) -> dict[int, str]:
    """Keep only well-formed words for the slides we asked for (0-based)."""
    items = raw.get("slides") if isinstance(raw, dict) else None
    found: dict[int, str] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("n")) - 1
        except (TypeError, ValueError):
            continue
        speech = str(item.get("speech") or "").strip()[:MAX_SPEECH]
        if index in targets and speech and index not in found:
            found[index] = speech
    return found


# ----------------------------------------------------------------- endpoint
async def _context(db: TeacherDatabase, lesson_id: UUID) -> tuple[dict[str, Any], dict[str, Any]]:
    async with db.transaction() as conn:
        lesson = await conn.fetchrow(
            "select title, topic, age_group::text as age_group from public.lessons where id = $1 and teacher_id = $2",
            lesson_id,
            db.teacher.id,
        )
        robot = await conn.fetchrow(
            "select robot_name, robot_style from public.teacher_settings where teacher_id = $1", db.teacher.id
        )
    if lesson is None:
        raise NotFoundError(LESSON_NOT_FOUND)
    return dict(lesson), dict(robot) if robot else {"robot_name": "روبو", "robot_style": "playful"}


@router.post("/narrate", response_model=NarrateResult, summary="The robot writes its own words for the deck")
async def narrate_lesson(
    lesson_id: UUID,
    data: NarrateRequest | None = None,
    db: TeacherDatabase = Depends(get_teacher_database),
    ai: AiClient = Depends(get_ai_client),
    limiter: AiRateLimiter = Depends(get_ai_limiter),
) -> NarrateResult:
    data = data or NarrateRequest()
    lesson, robot = await _context(db, lesson_id)
    repo = SlideRepository(db)
    slides = await repo.all(lesson_id) or []
    if not slides:
        raise ValidationFailedError(
            "أضيفي شرائح للدرس أولاً، بعدين الروبوت يجهّز كلامه", details=[{"field": "slides", "type": "empty"}]
        )
    if len(slides) > MAX_NARRATED_SLIDES:
        raise ValidationFailedError(
            f"الروبوت يجهّز كلام {MAX_NARRATED_SLIDES} شريحة كحد أقصى في المرة",
            details=[{"field": "slides", "type": "too_many"}],
        )
    targets = {i for i, s in enumerate(slides) if data.rewrite_all or not s["speech"] or s["speech_auto"]}
    kept = len(slides) - len(targets)
    if not targets:
        return NarrateResult(slides=[SlideOut(**s) for s in slides], written=0, kept=kept)

    limiter.check(db.teacher.id)
    prompt = narrate_prompt(lesson, robot["robot_name"], robot["robot_style"], slides, targets)
    system = prompts.system_prompt(lesson["age_group"])
    for attempt in range(2):
        try:
            raw = await ai.generate_json(system, prompt + (prompts.retry_note("لا يوجد كلام صالح") if attempt else ""))
        except AiReplyFormatError:
            continue
        found = pick_speeches(raw, targets)
        if found:
            if len(found) < len(targets):
                logger.info("ai narration covered %s of %s slides", len(found), len(targets))
            rows = await repo.save_narration(
                lesson_id, {slides[i]["id"]: text for i, text in found.items()}, data.rewrite_all
            )
            if rows is None:
                raise NotFoundError(LESSON_NOT_FOUND)
            return NarrateResult(slides=[SlideOut(**r) for r in rows], written=len(found), kept=kept)
    raise AiFailedError()
