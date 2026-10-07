from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


def error_body(code: str, message: str, status: int) -> dict:
    return {"error": {"code": code, "message": message, "status": status}}


async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(error_body(exc.code, exc.message, exc.status), status_code=exc.status)


async def http_error_handler(_: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        code, message = detail["code"], detail["message"]
    else:
        message = str(detail) if isinstance(detail, str) else "Request failed."
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 422: "VALIDATION_ERROR"}.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(error_body(code, message, exc.status_code), status_code=exc.status_code, headers=exc.headers)


async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(error_body("VALIDATION_ERROR", "Request validation failed.", 422), status_code=422)

