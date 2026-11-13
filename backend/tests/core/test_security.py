"""Token verification (AUTH-08, AUTH-11)."""

from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.security import TokenVerifier
from app.shared.errors.exceptions import AuthenticationError, ServiceUnavailableError


def test_valid_token_returns_teacher(verifier, make_token):
    tid = uuid4()
    teacher = verifier.verify(make_token(tid))
    assert teacher.id == tid
    assert teacher.email == "teacher@example.com"


def test_expired_token_is_rejected_with_session_message(verifier, make_token):
    with pytest.raises(AuthenticationError) as info:
        verifier.verify(make_token(uuid4(), expires_in=-60))
    assert "انتهت الجلسة" in info.value.message


@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        ({"aud": "anon"}, "wrong audience"),
        ({"iss": "https://evil.example.com/auth/v1"}, "wrong issuer"),
        ({"role": "anon"}, "anon role"),
        ({"role": "service_role"}, "service role token"),
        ({"is_anonymous": True}, "anonymous sign-in"),
    ],
)
def test_token_with_bad_claims_is_rejected(verifier, make_token, kwargs, label):
    with pytest.raises(AuthenticationError):
        verifier.verify(make_token(uuid4(), **kwargs))


def test_token_signed_by_another_key_is_rejected(verifier, make_token):
    other_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(AuthenticationError):
        verifier.verify(make_token(uuid4(), key=other_key))


def test_hs256_token_is_rejected(verifier, make_token):
    # Algorithm-confusion guard: a symmetric token must never be accepted.
    token = make_token(uuid4(), key="a-shared-secret-of-sufficient-length-1234", algorithm="HS256")
    with pytest.raises(AuthenticationError):
        verifier.verify(token)


def test_non_uuid_subject_is_rejected(verifier, make_token):
    with pytest.raises(AuthenticationError):
        verifier.verify(make_token("not-a-uuid"))


def test_garbage_token_is_rejected(verifier):
    with pytest.raises(AuthenticationError):
        verifier.verify("not.a.token")


def test_unreachable_key_server_is_a_503_not_a_401(make_token):
    def unreachable(_token: str):
        raise jwt.PyJWKClientConnectionError("cannot reach JWKS")

    broken = TokenVerifier(issuer="x", audience="authenticated", key_resolver=unreachable)
    with pytest.raises(ServiceUnavailableError):
        broken.verify(make_token(uuid4()))


def test_api_without_token_returns_401(client):
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_api_with_bad_token_returns_401(client):
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401
