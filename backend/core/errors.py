"""Errores de dominio. La API los traduce a respuestas HTTP con su ``status_code``."""

from __future__ import annotations

from typing import Any


class InventoryError(Exception):
    status_code = 400
    code = "invalid_request"

    def __init__(self, message: str, **extra: Any):
        super().__init__(message)
        self.message = message
        self.extra = extra


class NotFoundError(InventoryError):
    status_code = 404
    code = "not_found"


class ConflictError(InventoryError):
    status_code = 409
    code = "conflict"
