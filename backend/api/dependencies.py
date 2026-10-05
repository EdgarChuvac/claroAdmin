"""Estado compartido de la aplicación y dependencias de FastAPI."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from ..core import tracing
from ..core.settings import BASE_DIR, Settings
from ..db.firebase_client import create_firestore_handle, create_memory_handle
from ..repositories.inventory import InventoryRepository
from ..schemas.requests import validate_service_id
from ..services.catalog import Catalog, load_catalog
from ..services.excel_import import parse_inventory_excel
from ..services.excel_parser import normalize_sheet_name

logger = logging.getLogger("claro.api")

SAMPLE_EXCEL_PATH = BASE_DIR / "data" / "ejemplo_inventario_ips.xlsx"


class AppState:
    settings: Settings
    repo: InventoryRepository
    catalog: Catalog
    backend: str

def validated_sheet(value: str) -> str:
    normalized = normalize_sheet_name(value)
    if normalized is None:
        raise HTTPException(status_code=400, detail="Segmento inválido: use la red base /24, p. ej. 10.20.38.0.")
    return normalized

def service_id_param(value: str) -> str:
    try:
        return validate_service_id(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

def build_state(settings: Settings) -> AppState:
    state = AppState()
    state.settings = settings
    state.catalog = load_catalog(settings.config_dir)
    state.catalog.network_defaults.psk_monitoreo = settings.monitoreo_psk
    handle = create_memory_handle() if settings.data_backend == "memory" else create_firestore_handle(settings)
    state.backend = handle.backend
    state.repo = InventoryRepository(handle, settings.firestore_collection_prefix,
                                     settings.operations_retention_days)
    if settings.data_backend == "memory" and settings.memory_seed_sample and SAMPLE_EXCEL_PATH.is_file():
        blocks, ignored = parse_inventory_excel(SAMPLE_EXCEL_PATH.read_bytes())
        state.repo.import_inventory(blocks, mode="replace", filename=SAMPLE_EXCEL_PATH.name,
                                    operator="sistema", operation_id="SEED", ignored_sheets=ignored)
        logger.info("Inventario de demostración cargado en memoria")
    return state

def get_state(request: Request) -> AppState:
    return request.app.state.claro

def require_operator(request: Request) -> str:
    ctx = tracing.current()
    operator = ctx.operator if ctx else ""
    if not operator:
        raise HTTPException(status_code=400, detail="Indique su nombre de operador antes de realizar cambios.")
    return operator

StateDep = Annotated[AppState, Depends(get_state)]

OperatorDep = Annotated[str, Depends(require_operator)]

def serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize(v) for v in value]
    return value

def loopback_range(state: AppState) -> tuple[str, str]:
    d = state.catalog.network_defaults
    return d.loopback_pool_start, d.loopback_pool_end
