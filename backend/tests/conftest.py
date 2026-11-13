"""Shared test fixtures.

Tests run without Supabase or any network (NFR-025):
- tokens are signed with a throwaway EC key generated per test session,
- the repository is replaced by an in-memory fake.
Test data is fictional (rules section 6).
"""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import TokenVerifier
from app.main import create_app
from app.modules.teachers.router import get_teacher_repository

SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"


@pytest.fixture(scope="session")
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def make_token(signing_key: ec.EllipticCurvePrivateKey) -> Callable[..., str]:
    def _make(
        sub: str | UUID,
        *,
        expires_in: int = 3600,
        aud: str = "authenticated",
        iss: str = ISSUER,
        role: str = "authenticated",
        key: Any = None,
        algorithm: str = "ES256",
        **extra: Any,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": str(sub),
            "aud": aud,
            "iss": iss,
            "role": role,
            "iat": now,
            "exp": now + expires_in,
            "email": "teacher@example.com",
            **extra,
        }
        return jwt.encode(claims, key if key is not None else signing_key, algorithm=algorithm)

    return _make


@pytest.fixture
def verifier(signing_key: ec.EllipticCurvePrivateKey) -> TokenVerifier:
    public_key = signing_key.public_key()
    return TokenVerifier(issuer=ISSUER, audience="authenticated", key_resolver=lambda _token: public_key)


class FakeTeacherRepository:
    """In-memory stand-in for TeacherRepository, keyed by teacher id."""

    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}

    def add_teacher(self, teacher_id: UUID, display_name: str = "معلمة تجريبية") -> None:
        now = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
        self.rows[teacher_id] = {
            "id": teacher_id,
            "display_name": display_name,
            "created_at": now,
            "voice_volume": 80,
            "speech_rate": Decimal("1.00"),
            "answer_wait_seconds": 8,
            "no_answer_action": "repeat",
            "default_alert_lead_minutes": 5,
            "kids_mode_pin_hash": None,
            "privacy_notice_accepted_at": None,
            "settings_updated_at": now,
        }

    async def fetch_profile(self, teacher_id: UUID) -> dict[str, Any] | None:
        row = self.rows.get(teacher_id)
        if row is None:
            return None
        return {**row, "has_kids_mode_pin": row["kids_mode_pin_hash"] is not None}

    async def update_display_name(self, teacher_id: UUID, display_name: str) -> bool:
        if teacher_id not in self.rows:
            return False
        self.rows[teacher_id]["display_name"] = display_name
        return True

    async def update_settings(self, teacher_id: UUID, values: dict[str, Any]) -> bool:
        if teacher_id not in self.rows:
            return False
        self.rows[teacher_id].update(values)
        return True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        supabase_url=SUPABASE_URL,
        database_url="postgresql://unused:unused@localhost:5432/unused",
        cors_origins="http://localhost:5173",
    )


@pytest.fixture
def fake_repo() -> FakeTeacherRepository:
    return FakeTeacherRepository()


@pytest.fixture
def app(settings: Settings, verifier: TokenVerifier, fake_repo: FakeTeacherRepository) -> FastAPI:
    application = create_app(settings, connect_db=False)
    application.state.token_verifier = verifier
    application.dependency_overrides[get_teacher_repository] = lambda: fake_repo
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def teacher_id(fake_repo: FakeTeacherRepository) -> UUID:
    tid = uuid4()
    fake_repo.add_teacher(tid)
    return tid


@pytest.fixture
def auth_headers(make_token: Callable[..., str], teacher_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(teacher_id)}"}
