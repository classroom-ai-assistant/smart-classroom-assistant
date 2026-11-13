"""Verifying the teacher's Supabase access token.

Signing up, logging in and password reset happen in the browser against
Supabase Auth (decision A, 2026-11-13). The browser then sends the
access token to this API as `Authorization: Bearer <token>`.

The token is verified with Supabase's PUBLIC signing keys (JWKS), so this
server holds no Supabase secret for authentication. Only asymmetric
algorithms are accepted; HS256 is rejected to rule out algorithm-confusion
attacks.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.shared.errors.exceptions import AuthenticationError, ServiceUnavailableError

ALLOWED_ALGORITHMS = ["ES256", "RS256"]

KeyResolver = Callable[[str], Any]
"""Given the raw token, return the public key that signed it."""


@dataclass(frozen=True)
class CurrentTeacher:
    id: UUID
    email: str | None


class TokenVerifier:
    def __init__(self, *, issuer: str, audience: str, key_resolver: KeyResolver) -> None:
        self._issuer = issuer
        self._audience = audience
        self._key_resolver = key_resolver

    def verify(self, token: str) -> CurrentTeacher:
        try:
            key = self._key_resolver(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWKClientConnectionError as exc:
            # Could not reach Supabase to fetch the public keys: not the teacher's fault.
            raise ServiceUnavailableError() from exc
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("انتهت الجلسة، الرجاء تسجيل الدخول مرة أخرى") from exc
        except (jwt.PyJWTError, ValueError) as exc:
            raise AuthenticationError() from exc

        if claims.get("role") != "authenticated" or claims.get("is_anonymous") is True:
            raise AuthenticationError()

        try:
            teacher_id = UUID(str(claims["sub"]))
        except ValueError as exc:
            raise AuthenticationError() from exc

        return CurrentTeacher(id=teacher_id, email=claims.get("email"))


def build_jwks_resolver(jwks_url: str) -> KeyResolver:
    """Fetch and cache Supabase's public signing keys."""
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600)

    def resolve(token: str) -> Any:
        return client.get_signing_key_from_jwt(token).key

    return resolve


_bearer = HTTPBearer(auto_error=False)


def get_token_verifier(request: Request) -> TokenVerifier:
    return request.app.state.token_verifier


async def get_current_teacher(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> CurrentTeacher:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("الرجاء تسجيل الدخول")
    # Key lookup may hit the network on a cache miss, so keep it off the event loop.
    return await run_in_threadpool(verifier.verify, credentials.credentials)
