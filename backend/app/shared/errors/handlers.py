"""Turn exceptions into the standard error response."""

import logging

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.shared.errors.exceptions import AppError, ServiceUnavailableError, ValidationFailedError

logger = logging.getLogger("app.errors")


def _body(error: AppError) -> dict:
    return {"error": {"code": error.code, "message": error.message, "details": error.details}}


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(_body(exc), status_code=exc.status_code, headers=headers)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Name the field (DR-05) without echoing the submitted value back.
    details = [
        {"field": ".".join(str(part) for part in err["loc"] if part != "body"), "type": err["type"]}
        for err in exc.errors()
    ]
    return JSONResponse(_body(ValidationFailedError(details=details)), status_code=422)


async def _database_error(_: Request, exc: asyncpg.PostgresError) -> JSONResponse:
    if isinstance(exc, asyncpg.CheckViolationError | asyncpg.NotNullViolationError):
        return JSONResponse(_body(ValidationFailedError()), status_code=422)
    logger.error("database error: %s", type(exc).__name__)
    return JSONResponse(_body(AppError()), status_code=500)


async def _connection_error(_: Request, exc: Exception) -> JSONResponse:
    logger.error("database unavailable: %s", type(exc).__name__)
    return JSONResponse(_body(ServiceUnavailableError()), status_code=503)


async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s", type(exc).__name__)
    return JSONResponse(_body(AppError()), status_code=500)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(asyncpg.PostgresError, _database_error)  # type: ignore[arg-type]
    app.add_exception_handler(asyncpg.InterfaceError, _connection_error)
    app.add_exception_handler(OSError, _connection_error)
    app.add_exception_handler(Exception, _unexpected)
