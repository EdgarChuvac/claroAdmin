"""Consulta de la bitácora de operaciones (soporte)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...core import tracing
from ..dependencies import (
    StateDep,
    serialize,
)

logger = logging.getLogger("claro.api")
router = APIRouter()


@router.get("/api/operations/{operation_id}")
def get_operation(operation_id: str, state: StateDep) -> dict[str, Any]:
    operation_id = operation_id.strip().upper()
    if not tracing.OPERATION_ID_RE.match(operation_id):
        raise HTTPException(status_code=400, detail="Formato de ID de operación inválido (OP-AAAAMMDD-XXXXXXXXXXXX).")
    return serialize(state.repo.get_operation(operation_id))

@router.get("/api/operations")
def list_operations(
    state: StateDep,
    operator: str = Query(default="", max_length=80),
    service_id: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    ops = state.repo.list_operations(tracing.clean_text(operator, 80), tracing.clean_text(service_id, 100), limit)
    return {"operations": serialize(ops)}
