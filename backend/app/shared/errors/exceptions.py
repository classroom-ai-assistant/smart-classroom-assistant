"""Application errors.

Every error the API returns has the same shape:
    {"error": {"code": "...", "message": "<Arabic, for the teacher>", "details": [...]}}
Messages never expose internals (rules section 11).
"""

from typing import Any


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    message: str = "حدث خطأ غير متوقع، حاولي مرة أخرى"

    def __init__(self, message: str | None = None, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        self.details = details or []


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "الرجاء تسجيل الدخول مرة أخرى"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "العنصر غير موجود"


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_failed"
    message = "تحقّقي من الحقول المحددة"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "الخدمة غير متاحة حالياً، حاولي بعد قليل"
