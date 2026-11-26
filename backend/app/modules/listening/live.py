"""Live call with the robot (OpenAI Realtime over WebRTC), prototype.

The browser never sees the real OpenAI key. This endpoint mints a short-lived
client secret (10 minutes) for one call, with the robot's instructions
already inside: its name and character, the lesson, every slide in order and
the slide on screen now, and the safety rules. The browser then opens the
WebRTC call directly with OpenAI using that secret.

Internship prototype (team voices only). Nothing about the call is stored or
logged here. Review before any use with real children (see client.py).
"""

import logging
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.ai.deps import AiRateLimiter
from app.modules.ai.prompts import AGE_LABELS
from app.modules.lessons.service import LESSON_NOT_FOUND
from app.modules.slides.narration import PAUSE, STYLES, _sticker_labels, describe_slide
from app.modules.slides.service import SLIDE_NOT_FOUND
from app.shared.errors.exceptions import (
    AiBusyError,
    AiFailedError,
    AiRateLimitedError,
    AiUnavailableError,
    NotFoundError,
)

logger = logging.getLogger("app.listening")

router = APIRouter(prefix="/api/v1/lessons/{lesson_id}", tags=["listening"])

SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
CALLS_URL = "https://api.openai.com/v1/realtime/calls"
SESSION_SECONDS = 600
MAX_SLIDES_IN_CONTEXT = 40


class LiveSession(BaseModel):
    client_secret: str  # short-lived ("ek_..."), only for this call
    expires_at: int  # seconds since epoch
    model: str
    voice: str
    calls_url: str  # where the browser POSTs its SDP offer


class LiveConfig(BaseModel):
    api_key: str = Field(repr=False)
    model: str
    voice: str


def get_live_config(request: Request) -> LiveConfig:
    config = getattr(request.app.state, "live_config", None)
    if config is None:
        raise AiUnavailableError("المكالمة مع الروبوت غير مفعّلة حالياً")
    return config


def get_live_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.live_http


def get_live_limiter(request: Request) -> AiRateLimiter:
    return request.app.state.live_limiter


def live_instructions(
    lesson: dict[str, Any], robot: dict[str, Any], slides: list[dict[str, Any]], current: int | None
) -> str:
    labels = _sticker_labels()
    deck = "\n".join(
        f"{'▶ ' if i == current else ''}شريحة {i + 1}: {describe_slide(s, labels)}"
        for i, s in enumerate(slides[:MAX_SLIDES_IN_CONTEXT])
    )
    now = (
        f"الشريحة المعروضة الآن هي رقم {current + 1} (عليها العلامة ▶)، ركّز عليها."
        if current is not None
        else "لم تبدأ الشرائح بعد."
    )
    age = AGE_LABELS.get(lesson["age_group"], AGE_LABELS["mixed_3_6"])
    return (
        f"أنت روبوت تعليمي لطيف اسمك «{robot['robot_name']}»، تتكلم مباشرة بالصوت مع أطفال روضة أعمارهم {age} "
        "ومع معلمتهم في فصل بالمملكة العربية السعودية.\n"
        f"شخصيتك: {STYLES.get(robot['robot_style'], STYLES['playful'])}\n"
        f"الدرس: {lesson['title']} — {lesson['topic']}\n"
        f"شرائح الدرس:\n{deck}\n{now}\n"
        "طريقة الكلام:\n"
        "- تكلّم بالعربية الفصحى المبسّطة جداً بلهجة ودودة، وبجمل قصيرة، وبصوت دافئ وهادئ السرعة.\n"
        "- ردودك قصيرة: من جملة إلى ثلاث جمل، ثم اسأل سؤالاً صغيراً أو انتظر.\n"
        "- كن معلّماً بالأخذ والعطاء: اسأل «فهمتم؟»، «مين يعرف؟»، وامدح المحاولة دائماً حتى لو كان الجواب غلط، ثم صحّح بلطف.\n"
        "- إذا لم تفهم ما قيل فقل بلطف: «ما سمعتك زين، تعيدها؟».\n"
        "- التزم بموضوع الدرس؛ إذا سُئلت عن شيء بريء خارج الدرس فأجب باختصار ومرح ثم ارجع للدرس.\n"
        "قواعد الأمان (لا تخالفها أبداً):\n"
        "- لا تسأل أي طفل عن اسمه الكامل أو عمره أو بيته أو أهله أو صوره أو أي معلومة شخصية، ولا تحفظ شيئاً عن أحد.\n"
        "- لا محتوى مخيف أو عنيف أو غير مناسب للأطفال، والتزم بقيم المجتمع السعودي والثقافة الإسلامية.\n"
        "- إذا طُلب منك شيء غير مناسب أو خطر فارفض بلطف واقترح شيئاً عن الدرس، وإذا بدا أن طفلاً متضايق أو في خطر فقل له يكلّم معلمته الآن.\n"
        "- لا تدّعِ أنك إنسان، ولا تتظاهر بأنك المعلمة؛ المعلمة هي المسؤولة في الفصل.\n"
        f"- لا تنطق أي رموز أو علامات مثل {PAUSE}.\n"
        f"ابدأ المكالمة بتحية قصيرة: سلّم على الأطفال وقل اسمك «{robot['robot_name']}» واسألهم سؤالاً صغيراً عن الدرس."
    )


async def _context(db: TeacherDatabase, lesson_id: UUID, slide_id: UUID | None):
    async with db.transaction() as conn:
        lesson = await conn.fetchrow(
            "select title, topic, age_group::text as age_group from public.lessons where id = $1 and teacher_id = $2",
            lesson_id,
            db.teacher.id,
        )
        if lesson is None:
            raise NotFoundError(LESSON_NOT_FOUND)
        robot = await conn.fetchrow(
            "select robot_name, robot_style from public.teacher_settings where teacher_id = $1", db.teacher.id
        )
        slides = await conn.fetch(
            "select id, layout, question from public.slides where lesson_id = $1 and teacher_id = $2 order by order_index",
            lesson_id,
            db.teacher.id,
        )
    current = None
    if slide_id is not None:
        current = next((i for i, s in enumerate(slides) if s["id"] == slide_id), None)
        if current is None:
            raise NotFoundError(SLIDE_NOT_FOUND)
    robot_d = dict(robot) if robot else {"robot_name": "روبو", "robot_style": "playful"}
    return dict(lesson), robot_d, [dict(s) for s in slides], current


def _session_body(config: LiveConfig, instructions: str, with_audio_options: bool) -> dict[str, Any]:
    session: dict[str, Any] = {"type": "realtime", "model": config.model, "instructions": instructions}
    if with_audio_options:
        session["audio"] = {
            "output": {"voice": config.voice},
            "input": {"turn_detection": {"type": "semantic_vad"}},
        }
    return {"expires_after": {"anchor": "created_at", "seconds": SESSION_SECONDS}, "session": session}


def _log(response: httpx.Response) -> None:
    try:
        err = response.json().get("error") or {}
        detail = f"type={err.get('type')} code={err.get('code')} message={str(err.get('message'))[:200]}"
    except ValueError:
        detail = "no json body"
    logger.warning("openai realtime secret HTTP %s %s", response.status_code, detail)


@router.post("/live-session", response_model=LiveSession, summary="Start a live voice call with the robot (short-lived secret)")
async def start_live_session(
    lesson_id: UUID,
    slide_id: UUID | None = None,
    db: TeacherDatabase = Depends(get_teacher_database),
    config: LiveConfig = Depends(get_live_config),
    http: httpx.AsyncClient = Depends(get_live_http),
    limiter: AiRateLimiter = Depends(get_live_limiter),
) -> LiveSession:
    lesson, robot, slides, current = await _context(db, lesson_id, slide_id)
    limiter.check(db.teacher.id)
    instructions = live_instructions(lesson, robot, slides, current)
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    response = None
    for with_audio_options in (True, False):
        try:
            response = await http.post(SECRETS_URL, headers=headers, json=_session_body(config, instructions, with_audio_options))
        except httpx.HTTPError as exc:
            logger.warning("openai realtime secret network error: %s", type(exc).__name__)
            raise AiBusyError() from exc
        if response.status_code != 400:
            break
        _log(response)  # maybe an audio option was rejected; retry with the defaults
    assert response is not None
    if response.status_code == 429:
        _log(response)
        raise AiRateLimitedError()
    if response.status_code in {500, 502, 503, 504}:
        _log(response)
        raise AiBusyError()
    if response.status_code != 200:
        _log(response)
        raise AiFailedError("تعذّر فتح المكالمة مع الروبوت الآن")
    try:
        body = response.json()
        secret = str(body["value"])
        expires_at = int(body["expires_at"])
    except (ValueError, KeyError, TypeError) as exc:
        raise AiFailedError("تعذّر فتح المكالمة مع الروبوت الآن") from exc
    voice = (((body.get("session") or {}).get("audio") or {}).get("output") or {}).get("voice") or config.voice
    logger.info("openai realtime secret ok model=%s slides=%s", config.model, len(slides))
    return LiveSession(
        client_secret=secret, expires_at=expires_at, model=config.model, voice=str(voice), calls_url=CALLS_URL
    )
