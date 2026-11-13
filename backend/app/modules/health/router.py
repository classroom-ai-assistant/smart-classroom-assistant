"""Health checks.

/health      — the process is up (no database call).
/health/db   — the database answers.
"""

import asyncpg
from fastapi import APIRouter, Depends

from app.database.connection import get_pool
from app.shared.errors.exceptions import ServiceUnavailableError

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/db")
async def health_db(pool: asyncpg.Pool = Depends(get_pool)) -> dict[str, str]:
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("select 1")
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
        raise ServiceUnavailableError() from exc
    return {"status": "ok"}
