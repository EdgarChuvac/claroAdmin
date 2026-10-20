"""Topología (islas y chasis), segmentos por isla, catálogo de VLANs (RD/VRF) y loopbacks."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Query

from ...core import tracing
from ...core.errors import InventoryError
from ...schemas.requests import (
    CHASIS_ID_PATTERN,
    ChasisRequest,
    IslaRequest,
    SheetIslaRequest,
    VlanRequest,
)
from ..dependencies import (
    OperatorDep,
    StateDep,
    loopback_range,
    serialize,
    validated_sheet,
)

logger = logging.getLogger("claro.api")
router = APIRouter()


def _region(state, value: str) -> str:
    try:
        return state.catalog.region(value)
    except ValueError as exc:
        raise InventoryError(str(exc)) from exc


@router.get("/api/islas")
def list_islas(
    state: StateDep,
    region: str | None = Query(default=None, max_length=40),
) -> dict[str, Any]:
    """Islas de una región (colección ``islas``) o, sin región, todas las conocidas."""
    unassigned = any(not s.get("isla") for s in state.repo.list_sheets())
    if region is not None:
        region = _region(state, region)
        detalle = state.repo.list_islas_region(region)
        return {"region": region, "islas": [d["nombre"] for d in detalle], "detalle": serialize(detalle),
                "has_unassigned": unassigned}
    islas = set(state.repo.list_islas())
    islas |= {c.isla.upper() for c in state.catalog.centrales if c.isla}
    return {"islas": sorted(islas), "has_unassigned": unassigned}

@router.put("/api/islas")
def upsert_isla(req: IslaRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    region = _region(state, req.region)
    tracing.audit("topologia.isla", isla=req.nombre, region=region, activo=req.activo)
    doc = state.repo.upsert_isla(tracing.clean_text(req.nombre, 60), region, operator,
                                 tracing.current_operation_id(), req.activo)
    return {"message": f"Isla {doc['nombre']} guardada en la región {region}.", "isla": serialize(doc),
            "operation_id": tracing.current_operation_id()}

@router.get("/api/chasis")
def list_chasis(state: StateDep, isla: str = Query(min_length=1, max_length=60, pattern=r"\S")) -> dict[str, Any]:
    """Chasis activos de una isla registrada en la topología."""
    return {"isla": isla.strip().upper(), "chasis": serialize(state.repo.list_chasis_isla(isla.strip()))}

@router.put("/api/chasis/{chasis_id}")
def upsert_chasis(chasis_id: str, req: ChasisRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    if not re.fullmatch(CHASIS_ID_PATTERN, chasis_id):
        raise InventoryError("ID de chasis inválido: use letras, números, guion o guion bajo (máx. 64).")
    tracing.audit("topologia.chasis", chasis_id=chasis_id, isla=req.isla, activo=req.activo)
    values = {k: tracing.clean_text(getattr(req, k), 80) for k in state.repo.CHASIS_TEXT_FIELDS}
    values.update(slots=[tracing.clean_text(v, 20) for v in req.slots],
                  puertos=[tracing.clean_text(v, 20) for v in req.puertos],
                  equipos_ruta=req.equipos_ruta, activo=req.activo)
    doc = state.repo.upsert_chasis(chasis_id, tracing.clean_text(req.isla, 60), values, operator,
                                   tracing.current_operation_id())
    return {"message": f"Chasis {doc['nombre']} guardado en la isla {doc['isla']}.", "chasis": serialize(doc),
            "operation_id": tracing.current_operation_id()}


@router.get("/api/segments")
def list_segments(state: StateDep, isla: str | None = Query(default=None, max_length=60)) -> dict[str, Any]:
    """Subredes de una isla (``isla=`` vacío = segmentos sin isla asignada)."""
    isla = None if isla is None else tracing.clean_text(isla, 60)
    return {"isla": isla, "segments": serialize(state.repo.list_segments(isla))}

@router.put("/api/sheets/{sheet}/isla")
def set_sheet_isla(sheet: str, req: SheetIslaRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    sheet = validated_sheet(sheet)
    tracing.audit("inventory.set_isla", sheet=sheet, isla=req.isla)
    result = state.repo.set_sheet_isla(sheet, tracing.clean_text(req.isla, 60))
    return {"message": f"Segmento {sheet} asignado a la isla {result['isla']}.", **result,
            "operation_id": tracing.current_operation_id()}

@router.get("/api/vlans")
def list_vlans(state: StateDep, isla: str = Query(default="", max_length=60)) -> dict[str, Any]:
    return {"vlans": serialize(state.repo.list_vlans(tracing.clean_text(isla, 60)))}


@router.get("/api/equipos")
def list_equipos(state: StateDep, chasis_id: str = Query(min_length=1, max_length=64)) -> dict[str, Any]:
    """Ruta ordenada de equipos del chasis seleccionado, leída desde Firebase."""
    chasis_id = tracing.clean_text(chasis_id, 64)
    return {"equipos": serialize(state.repo.list_equipos_ruta_chasis(chasis_id))}

@router.put("/api/vlans")
def upsert_vlan(req: VlanRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    tracing.audit("vlan.upsert", isla=req.isla, vlan=req.vlan)
    doc = state.repo.upsert_vlan(
        tracing.clean_text(req.isla, 60), req.vlan.strip(),
        {
            **{
                k: tracing.clean_text(getattr(req, k), 120)
                for k in ("rd", "vrf_name", "vrf_desc", "vlan_desc")
            },
            "config": re.sub(
                r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "",
                req.config.replace("\r\n", "\n").replace("\r", "\n"),
            )[:500],
        },
        operator, tracing.current_operation_id(),
    )
    return {"message": f"Datos de la VLAN {doc['vlan']} guardados.", "vlan": serialize(doc),
            "operation_id": tracing.current_operation_id()}

@router.get("/api/loopbacks/next")
def next_loopback(state: StateDep, service_id: str = Query(default="", max_length=100)) -> dict[str, Any]:
    service_id = tracing.clean_text(service_id, 100)
    ip = state.repo.peek_loopback(service_id, *loopback_range(state))
    return {"ip": ip, "cidr": f"{ip}/32", "assigned": state.repo.loopback_for_service(service_id) == ip}
