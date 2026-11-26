"""POST /api/v1/lessons/{lesson_id}/slides/{slide_id}/listen

The tablet records the children's answer after the robot asks the slide's
question and sends the raw audio as the request body (Content-Type
audio/webm, audio/ogg, audio/wav, audio/mp4 or audio/mpeg; up to 2 MB,
about 15 seconds). The server turns it into text, compares it with the
question's expected answers and says what the robot should do next:

- correct: praise (matched = the expected answer that was heard)
- wrong:   give the hint, or ask again
- silent:  nothing understood -> ask the simpler question
- heard:   the slide has no expected answers; just what was heard

Nothing is stored and the transcript is never logged.
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.database.rls_session import TeacherDatabase, get_teacher_database
from app.modules.ai.deps import AiRateLimiter
from app.modules.listening.client import Transcriber
from app.modules.listening.matching import match
from app.modules.slides.service import SLIDE_NOT_FOUND
from app.shared.errors.exceptions import AiUnavailableError, NotFoundError, ValidationFailedError

router = APIRouter(prefix="/api/v1/lessons/{lesson_id}/slides/{slide_id}", tags=["listening"])

MAX_AUDIO_BYTES = 2 * 1024 * 1024
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/mpeg"}


class ListenResult(BaseModel):
    result: Literal["correct", "wrong", "silent", "heard"]
    heard: str
    matched: str | None = None
    # What the robot can say next, from the slide's own question.
    hint: str | None = None
    simpler_question: str | None = None


def get_transcriber(request: Request) -> Transcriber:
    client = getattr(request.app.state, "transcriber", None)
    if client is None:
        raise AiUnavailableError("خدمة السماع غير مفعّلة حالياً")
    return client


def get_listen_limiter(request: Request) -> AiRateLimiter:
    return request.app.state.listen_limiter


async def _read_audio(request: Request) -> tuple[bytes, str]:
    mime = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if mime not in AUDIO_TYPES:
        raise ValidationFailedError("نوع التسجيل غير مدعوم", details=[{"field": "audio", "type": "not_allowed"}])
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        raise ValidationFailedError("التسجيل طويل، خليه أقل من 15 ثانية", details=[{"field": "audio", "type": "too_large"}])
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_AUDIO_BYTES:
            raise ValidationFailedError("التسجيل طويل، خليه أقل من 15 ثانية", details=[{"field": "audio", "type": "too_large"}])
    if len(body) < 100:
        raise ValidationFailedError("التسجيل فاضي", details=[{"field": "audio", "type": "empty"}])
    return bytes(body), mime


@router.post(
    "/listen",
    response_model=ListenResult,
    summary="Hear the children's answer to the slide's question (audio body, not stored)",
    openapi_extra={"requestBody": {"content": {t: {"schema": {"type": "string", "format": "binary"}} for t in sorted(AUDIO_TYPES)}, "required": True}},
)
async def listen(
    lesson_id: UUID,
    slide_id: UUID,
    request: Request,
    db: TeacherDatabase = Depends(get_teacher_database),
    transcriber: Transcriber = Depends(get_transcriber),
    limiter: AiRateLimiter = Depends(get_listen_limiter),
) -> ListenResult:
    async with db.transaction() as conn:
        question = await conn.fetchval(
            "select coalesce(question, '{}'::jsonb) from public.slides where id = $1 and lesson_id = $2 and teacher_id = $3",
            slide_id,
            lesson_id,
            db.teacher.id,
        )
    if question is None:
        raise NotFoundError(SLIDE_NOT_FOUND)
    audio, mime = await _read_audio(request)
    limiter.check(db.teacher.id)
    expected = [str(a) for a in (question.get("expected_answers") or []) if str(a).strip()][:20]
    heard = await transcriber.transcribe(audio, mime, expected)
    extra = {"hint": question.get("hint"), "simpler_question": question.get("simpler_question")}
    if not heard:
        return ListenResult(result="silent", heard="", **extra)
    if not expected:
        return ListenResult(result="heard", heard=heard, **extra)
    found = match(heard, expected)
    return ListenResult(result="correct" if found else "wrong", heard=heard, matched=found, **extra)
