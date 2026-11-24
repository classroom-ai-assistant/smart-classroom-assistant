"""POST /api/v1/speech: read lesson text aloud in the robot's voice (PoC)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.core.security import CurrentTeacher, get_current_teacher
from app.modules.ai.deps import AiRateLimiter
from app.modules.speech.client import VOICES, SpeechClient
from app.shared.errors.exceptions import AiUnavailableError

router = APIRouter(prefix="/api/v1/speech", tags=["speech"])

Voice = Literal[VOICES]  # type: ignore[valid-type]


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]
    voice: Voice = "Puck"  # type: ignore[assignment]


def get_speech_client(request: Request) -> SpeechClient:
    client = getattr(request.app.state, "speech_client", None)
    if client is None:
        raise AiUnavailableError("خدمة الصوت غير مفعّلة حالياً")
    return client


def get_speech_limiter(request: Request) -> AiRateLimiter:
    return request.app.state.speech_limiter


@router.post(
    "",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
    summary="Text to speech in the robot's voice (WAV, not stored)",
)
async def speak(
    data: SpeechRequest,
    teacher: CurrentTeacher = Depends(get_current_teacher),
    client: SpeechClient = Depends(get_speech_client),
    limiter: AiRateLimiter = Depends(get_speech_limiter),
) -> Response:
    limiter.check(teacher.id)
    audio = await client.synthesize(data.text, data.voice)
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
