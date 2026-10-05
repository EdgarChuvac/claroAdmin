"""Salud, estado, configuración y catálogo de centrales."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from ... import __version__ as APP_VERSION
from ...core import tracing
from ...services.catalog import Central, load_catalog
from ..dependencies import (
    OperatorDep,
    StateDep,
    serialize,
)

logger = logging.getLogger("claro.api")
router = APIRouter()


@router.get("/api/health")
def health(state: StateDep) -> dict[str, Any]:
    state.repo.ping()
    return {"status": "ok", "backend": state.backend, "version": APP_VERSION}

@router.get("/api/status")
def get_status(state: StateDep) -> dict[str, Any]:
    sheets = state.repo.list_sheets()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "backend": state.backend,
        "environment": state.settings.app_env,
        "inventory": {
            "sheets": len(sheets),
            "available": sum(s.get("available_count", 0) for s in sheets),
            "assigned": sum(s.get("assigned_count", 0) for s in sheets),
        },
        "operation_id": tracing.current_operation_id(),
    }

@router.get("/api/config")
def get_config(state: StateDep) -> dict[str, Any]:
    centrales = state.repo.list_centrales()
    source = "firestore"
    if not centrales:
        centrales = [c.model_dump() for c in state.catalog.centrales]
        source = "archivo"
    return {
        **state.catalog.to_public_dict(),
        "centrales": serialize(centrales),
        "centrales_source": source,
        "max_upload_mb": state.settings.max_upload_mb,
        "backend": state.backend,
        "version": APP_VERSION,
    }

@router.post("/api/centrales/sync")
def sync_centrales(state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    """Carga el catálogo de ``config/centrales.json`` en Firestore."""
    centrales = [Central(**c.model_dump()).model_dump() for c in load_catalog(state.settings.config_dir).centrales]
    count = state.repo.replace_centrales(centrales)
    tracing.audit("centrales.sync", count=count)
    return {"message": f"{count} central(es) sincronizada(s).", "operation_id": tracing.current_operation_id()}
