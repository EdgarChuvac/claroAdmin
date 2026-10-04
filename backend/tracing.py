"""Trazabilidad: ID único por operación, logs estructurados y auditoría.

Cada petición HTTP recibe un ``operation_id`` con el formato
``OP-AAAAMMDD-XXXXXXXXXXXX`` (fecha UTC + 12 caracteres hexadecimales
aleatorios). El ID:

* se devuelve en el encabezado ``X-Operation-ID`` y en el cuerpo JSON,
* aparece en cada línea de log emitida durante la petición,
* se guarda en la colección ``operations`` de Firestore (escrituras y errores),
* se muestra al usuario en la interfaz para que lo comparta con soporte.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from .settings import Settings

OPERATION_ID_RE = re.compile(r"^OP-\d{8}-[0-9A-F]{12}$")
OPERATOR_MAX_LEN = 80
_SAFE_TEXT_RE = re.compile(r"[\x00-\x1f\x7f]")


def new_operation_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"OP-{now:%Y%m%d}-{secrets.token_hex(6).upper()}"


def clean_text(value: str | None, max_len: int = 200) -> str:
    """Elimina caracteres de control (evita inyección de líneas en logs)."""
    if not value:
        return ""
    return _SAFE_TEXT_RE.sub(" ", value).strip()[:max_len]


@dataclass
class OperationContext:
    operation_id: str
    method: str = ""
    path: str = ""
    operator: str = ""
    client_session: str = ""
    client_ip: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_perf: float = field(default_factory=time.perf_counter)
    action: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    persist: bool = False

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started_perf) * 1000)


_current: contextvars.ContextVar[OperationContext | None] = contextvars.ContextVar(
    "operation_context", default=None
)


def set_context(ctx: OperationContext | None) -> contextvars.Token:
    return _current.set(ctx)


def reset_context(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> OperationContext | None:
    return _current.get()


def current_operation_id() -> str:
    ctx = _current.get()
    return ctx.operation_id if ctx else ""


def audit(action: str, **details: Any) -> None:
    """Marca la operación actual con una acción de negocio y sus detalles.

    Las operaciones marcadas se guardan en la colección ``operations``.
    """
    ctx = _current.get()
    if ctx is None:
        return
    ctx.action = action
    ctx.details.update(details)
    ctx.persist = True


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _current.get()
        record.operation_id = ctx.operation_id if ctx else "-"
        record.operator = (ctx.operator or "-") if ctx else "-"
        return True


class JsonFormatter(logging.Formatter):
    RESERVED = set(vars(logging.makeLogRecord({}))) | {"operation_id", "operator", "message"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "severity": record.levelname,  # Google Cloud Logging lo usa como nivel
            "logger": record.name,
            "operation_id": getattr(record, "operation_id", "-"),
            "operator": getattr(record, "operator", "-"),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


TEXT_FORMAT = "%(asctime)s %(levelname)-7s [%(operation_id)s] [%(operator)s] %(name)s: %(message)s"


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_claro_handler", False):
            root.removeHandler(handler)
    root.setLevel(settings.log_level)

    formatter: logging.Formatter
    formatter = JsonFormatter() if settings.log_format == "json" else logging.Formatter(TEXT_FORMAT)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.log_dir:
        try:
            settings.log_path.mkdir(parents=True, exist_ok=True)
            handlers.append(
                RotatingFileHandler(
                    settings.log_path / "app.log",
                    maxBytes=settings.log_file_max_mb * 1024 * 1024,
                    backupCount=settings.log_file_backups,
                    encoding="utf-8",
                )
            )
        except OSError:
            logging.getLogger(__name__).warning("No se pudo crear el directorio de logs %s", settings.log_path)

    context_filter = ContextFilter()
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        handler._claro_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    # Uvicorn ya registra cada petición; nuestro middleware lo hace con el ID.
    logging.getLogger("uvicorn.access").disabled = True
