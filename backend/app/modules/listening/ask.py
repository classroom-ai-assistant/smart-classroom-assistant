"""Ask the robot: a free question about the lesson, by voice or text.

POST /api/v1/lessons/{lesson_id}/ask[?slide_id=...]
- audio body (same types and limit as /listen) -> transcribed first, or
- JSON {"question": "..."} typed by the teacher.

The robot answers in its own character, in one to three short sentences,
about the lesson and the current slide. Off-topic or unsuitable questions
are gently brought back to the lesson. Internship prototype (team voices):
the question and answer are never stored or logged.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.ai import prompts
from app.modules.ai.client import AiClient, AiReplyFormatError
from app.modules.ai.deps import AiRateLimiter, get_ai_client
from app.modules.lessons.service import LESSON_NOT_FOUND
from app.modules.listening.router import _read_audio, get_transcriber
from app.modules.slides.narration import STYLES, _sticker_labels, describe_slide
from app.modules.slides.service import SLIDE_NOT_FOUND
from app.shared.errors.exceptions import AiFailedError, NotFoundError, ValidationFailedError

router = APIRouter(prefix="/api/v1/lessons/{lesson_id}", tags=["listening"])

MAX_ANSWER = 600


class TextQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class AskResult(BaseModel):
    heard: str  # the question as understood ("" if nothing was understood)
    answer: str | None  # None when nothing was understood: the robot asks to repeat


def get_ask_limiter(request: Request) -> AiRateLimiter:
    return request.app.state.ask_limiter


def ask_prompt(lesson: dict[str, Any], robot: dict[str, Any], slide: str | None, question: str) -> str:
    return (
        f"عنوان الدرس: {lesson['title']}\nموضوع الدرس: {lesson['topic']}\n"
        + (f"الشريحة المعروضة الآن: <<<{slide}>>>\n" if slide else "")
        + f"أنت الروبوت الذي يقدّم الدرس، واسمك: <<<{robot['robot_name']}>>>.\n"
        + f"شخصيتك: {STYLES.get(robot['robot_style'], STYLES['playful'])}\n"
        + f"سألك أحد في الفصل هذا السؤال: <<<{question}>>>\n"
        + "أجب بصوتك كروبوت، من جملة إلى ثلاث جمل قصيرة جداً يفهمها طفل الروضة.\n"
        + "- إذا كان السؤال عن الدرس أو عن شيء في الشريحة فأجب بدقة وبمثال من حياة الطفل.\n"
        + "- إذا كان خارج الدرس لكنه بريء (مثل: كم عمرك؟ هل تحب التفاح؟) فأجب بلطف ومرح باختصار ثم ارجع للدرس.\n"
        + "- إذا كان غير مناسب للأطفال أو لم تفهمه فلا تجب عنه؛ قل بلطف إنك تحب الأسئلة عن الدرس واقترح سؤالاً عنه.\n"
        + "- لا تعطِ معلومات شخصية ولا تطلب أي معلومة من الأطفال، ولا تخترع معلومات غير صحيحة.\n"
        + 'أجب بالشكل: {"answer": "..."}'
    )


async def _context(db: TeacherDatabase, lesson_id: UUID, slide_id: UUID | None) -> tuple[dict, dict, str | None]:
    async with db.transaction() as conn:
        lesson = await conn.fetchrow(
            "select title, topic, age_group::text as age_group from public.lessons where id = $1 and teacher_id = $2",
            lesson_id,
            db.teacher.id,
        )
        robot = await conn.fetchrow(
            "select robot_name, robot_style from public.teacher_settings where teacher_id = $1", db.teacher.id
        )
        slide = None
        if lesson is not None and slide_id is not None:
            slide = await conn.fetchrow(
                "select layout, question from public.slides where id = $1 and lesson_id = $2 and teacher_id = $3",
                slide_id,
                lesson_id,
                db.teacher.id,
            )
            if slide is None:
                raise NotFoundError(SLIDE_NOT_FOUND)
    if lesson is None:
        raise NotFoundError(LESSON_NOT_FOUND)
    robot_d = dict(robot) if robot else {"robot_name": "روبو", "robot_style": "playful"}
    described = describe_slide(dict(slide), _sticker_labels()) if slide else None
    return dict(lesson), robot_d, described


async def _question_from(request: Request) -> tuple[str | None, tuple[bytes, str] | None]:
    mime = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if mime == "application/json":
        try:
            return TextQuestion.model_validate_json(await request.body()).question, None
        except ValidationError as exc:
            raise ValidationFailedError(details=[{"field": "question", "type": "invalid"}]) from exc
    return None, await _read_audio(request)


@router.post(
    "/ask",
    response_model=AskResult,
    summary="Ask the robot a question by voice (audio body) or text (JSON); nothing is stored",
)
async def ask_robot(
    lesson_id: UUID,
    request: Request,
    slide_id: UUID | None = None,
    db: TeacherDatabase = Depends(get_teacher_database),
    ai: AiClient = Depends(get_ai_client),
    limiter: AiRateLimiter = Depends(get_ask_limiter),
) -> AskResult:
    lesson, robot, slide = await _context(db, lesson_id, slide_id)
    text, audio = await _question_from(request)
    limiter.check(db.teacher.id)
    if audio is not None:
        text = await get_transcriber(request).transcribe(audio[0], audio[1], [])
    question = " ".join((text or "").split())[:300]
    if not question:
        return AskResult(heard="", answer=None)
    prompt = ask_prompt(lesson, robot, slide, question)
    system = prompts.system_prompt(lesson["age_group"])
    for attempt in range(2):
        try:
            raw = await ai.generate_json(system, prompt + (prompts.retry_note("لا توجد إجابة") if attempt else ""))
        except AiReplyFormatError:
            continue
        answer = str(raw.get("answer") or "").strip() if isinstance(raw, dict) else ""
        if answer:
            return AskResult(heard=question, answer=answer[:MAX_ANSWER])
    raise AiFailedError()
