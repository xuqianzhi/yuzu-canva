"""Every non-2xx response has an ErrorResponse body."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .contract import ErrorCode, ErrorDetail, ErrorResponse


class ApiError(Exception):
    """Raise from a route to send an ErrorResponse."""

    def __init__(
        self,
        status: int,
        code: ErrorCode,
        message: str,
        context: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.detail = ErrorDetail(code=code, message=message, context=context or {})


def _body(detail: ErrorDetail) -> dict:
    return ErrorResponse(error=detail).model_dump(mode="json")


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.detail), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()))
        reason = first.get("msg", "invalid request")
        message = f"{where}: {reason}" if where else reason
        detail = ErrorDetail(code=ErrorCode.validation_error, message=message)
        return JSONResponse(_body(detail), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.not_found if exc.status_code == 404 else ErrorCode.validation_error
        detail = ErrorDetail(code=code, message=str(exc.detail))
        return JSONResponse(_body(detail), status_code=exc.status_code)


def responses(*statuses: int) -> dict[int | str, dict]:
    """OpenAPI `responses=` entry declaring ErrorResponse for these statuses."""
    return {s: {"model": ErrorResponse} for s in (*statuses, 422)}
