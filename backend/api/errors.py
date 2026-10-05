"""Traducción de errores a respuestas JSON que siempre incluyen el ID de operación."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core import tracing
from ..core.errors import InventoryError

logger = logging.getLogger("claro.api")


def _error_response(request: Request, status_code: int, detail: Any, code: str) -> JSONResponse:
    request.state.error_detail = detail if isinstance(detail, str) else code
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "code": code, "operation_id": tracing.current_operation_id()},
    )

async def inventory_error_handler(request: Request, exc: InventoryError):
    return _error_response(request, exc.status_code, exc.message, exc.code)

async def http_error_handler(request: Request, exc: StarletteHTTPException):
    return _error_response(request, exc.status_code, exc.detail, "http_error")

async def validation_error_handler(request: Request, exc: RequestValidationError):
    messages = []
    for err in exc.errors():
        location = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "data"))
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        messages.append(f"{location}: {msg}" if location else msg)
    return _error_response(request, 422, "; ".join(messages) or "Solicitud inválida.", "validation_error")

async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Error no controlado")
    return _error_response(
        request, 500,
        "Error interno. Comparta el ID de operación con soporte técnico.", "internal_error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(InventoryError, inventory_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
