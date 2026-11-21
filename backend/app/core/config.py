"""Application settings, read from environment variables / .env.

Secrets are wrapped in SecretStr so they never appear in logs or reprs.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"

    supabase_url: AnyHttpUrl
    database_url: SecretStr

    # Supabase access tokens for signed-in users carry aud = "authenticated".
    jwt_audience: str = "authenticated"

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    db_pool_min_size: int = Field(default=1, ge=0)
    db_pool_max_size: int = Field(default=10, ge=1)

    # AI content (slice 3). Without a key the AI endpoints answer 503 and
    # everything else keeps working. The key lives only in the host's env.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_seconds: float = Field(default=60, gt=0)
    # Per-teacher cap on AI calls, protecting the API quota.
    ai_requests_per_hour: int = Field(default=30, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def supabase_base(self) -> str:
        return str(self.supabase_url).rstrip("/")

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_base}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_base}/auth/v1/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
