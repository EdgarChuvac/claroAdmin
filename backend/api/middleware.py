"""Middleware de trazabilidad: asigna un ID de operación a cada petición y la audita."""

from __future__ import annotations

import logging
from urllib.parse import unquote

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ..core import tracing
from .dependencies import AppState, serialize

logger = logging.getLogger("claro.api")


async def operation_tracing(request: Request, call_next):
    ctx = tracing.OperationContext(
        operation_id=tracing.new_operation_id(),
        method=request.method,
        path=request.url.path,
        operator=tracing.clean_text(unquote(request.headers.get("x-operator", "")), tracing.OPERATOR_MAX_LEN),
        client_session=tracing.clean_text(request.headers.get("x-client-session", ""), 64),
        client_ip=request.client.host if request.client else "",
    )
    token = tracing.set_context(ctx)
    status_code = 500
    error: str | None = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        error = getattr(request.state, "error_detail", None)
        response.headers["X-Operation-ID"] = ctx.operation_id
        return response
    except Exception:
        # Los errores no controlados se atienden aquí (y no en ServerErrorMiddleware)
        # para que la respuesta conserve el ID de operación.
        logger.exception("Error no controlado")
        status_code = 500
        error = "internal_error"
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno. Comparta el ID de operación con soporte técnico.",
                     "code": "internal_error", "operation_id": ctx.operation_id},
            headers={"X-Operation-ID": ctx.operation_id},
        )
    finally:
        is_api = ctx.path.startswith("/api/")
        level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
        if is_api or status_code >= 400:
            logger.log(level, "%s %s -> %s", ctx.method, ctx.path, status_code, extra={
                "status_code": status_code, "duration_ms": ctx.elapsed_ms(),
                "action": ctx.action or None, "client_ip": ctx.client_ip,
                "client_session": ctx.client_session or None,
            })
        state: AppState | None = getattr(request.app.state, "claro", None)
        should_persist = is_api and (
            ctx.persist or (status_code >= 400 and status_code not in (404, 405)) or
            (state is not None and state.settings.persist_read_operations)
        )
        if state is not None and should_persist and ctx.path != "/api/health":
            record = {
                "operation_id": ctx.operation_id,
                "action": ctx.action or f"{ctx.method} {ctx.path}",
                "method": ctx.method,
                "path": ctx.path,
                "status_code": status_code,
                "outcome": "ok" if status_code < 400 else "error",
                "operator": ctx.operator or None,
                "client_session": ctx.client_session or None,
                "client_ip": ctx.client_ip or None,
                "duration_ms": ctx.elapsed_ms(),
                "service_id": ctx.details.get("service_id"),
                "details": serialize(ctx.details),
                "error": error,
                "created_at": ctx.started_at,
            }
            try:
                await run_in_threadpool(state.repo.save_operation, record)
            except Exception:  # la auditoría nunca debe romper la respuesta
                logger.exception("No se pudo guardar la operación en Firestore")
        tracing.reset_context(token)
