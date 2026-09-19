from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="unset")


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


class AppError(Exception):
    """Raised by routes/services; converted to the standard error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        field: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field
        self.retryable = retryable
        self.details = details or {}

    def envelope(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "field": self.field,
                "retryable": self.retryable,
                "details": self.details,
            },
            "request_id": get_request_id(),
        }


def ok(data: Any) -> dict[str, Any]:
    return {"data": data, "request_id": get_request_id()}


def not_found(what: str) -> AppError:
    return AppError("NOT_FOUND", f"{what} not found", status_code=404)


def unauthorized(message: str = "Missing or invalid credentials") -> AppError:
    return AppError("UNAUTHORIZED", message, status_code=401)


def forbidden(message: str = "Invalid credentials") -> AppError:
    return AppError("FORBIDDEN", message, status_code=403)
