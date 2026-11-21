"""Wiring for the AI client and a per-teacher request cap."""

import time
from collections import defaultdict, deque
from uuid import UUID

from fastapi import Request

from app.modules.ai.client import AiClient
from app.shared.errors.exceptions import AiRateLimitedError, AiUnavailableError


class AiRateLimiter:
    """Sliding one-hour window per teacher, in memory.

    Good enough for a single API instance; a multi-instance deployment would
    need a shared store.
    """

    WINDOW_SECONDS = 3600

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._calls: dict[UUID, deque[float]] = defaultdict(deque)

    def check(self, teacher_id: UUID, cost: int = 1) -> None:
        now = time.monotonic()
        calls = self._calls[teacher_id]
        while calls and now - calls[0] >= self.WINDOW_SECONDS:
            calls.popleft()
        if len(calls) + cost > self._limit:
            raise AiRateLimitedError()
        calls.extend([now] * cost)


def get_ai_client(request: Request) -> AiClient:
    client = getattr(request.app.state, "ai_client", None)
    if client is None:
        raise AiUnavailableError()
    return client


def get_ai_limiter(request: Request) -> AiRateLimiter:
    return request.app.state.ai_limiter
