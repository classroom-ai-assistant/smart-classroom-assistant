"""Database connection pool (asyncpg).

statement_cache_size=0 keeps the pool compatible with Supabase's poolers,
which do not support prepared statements in transaction mode.
"""

import asyncpg
from fastapi import Request

from app.core.config import Settings


async def create_pool(settings: Settings) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.database_url.get_secret_value(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        statement_cache_size=0,
        command_timeout=10,
    )


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool
