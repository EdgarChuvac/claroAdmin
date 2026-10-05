"""Islas, segmentos por isla, catálogo de VLANs (RD/VRF) y loopbacks."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from ...core import tracing
from ...schemas.requests import (
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


@router.get("/api/islas")
def list_islas(state: StateDep) -> dict[str, Any]:
    islas = set(state.repo.list_islas())
    islas |= {c.isla.upper() for c in state.catalog.centrales if c.isla}
    unassigned = any(not s.get("isla") for s in state.repo.list_sheets())
    return {"islas": sorted(islas), "has_unassigned": unassigned}

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

@router.put("/api/vlans")
def upsert_vlan(req: VlanRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    tracing.audit("vlan.upsert", isla=req.isla, vlan=req.vlan)
    doc = state.repo.upsert_vlan(
        tracing.clean_text(req.isla, 60), req.vlan.strip(),
        {k: tracing.clean_text(getattr(req, k), 120) for k in ("rd", "vrf_name", "vrf_desc", "vlan_desc")},
        operator, tracing.current_operation_id(),
    )
    return {"message": f"Datos de la VLAN {doc['vlan']} guardados.", "vlan": serialize(doc),
            "operation_id": tracing.current_operation_id()}

@router.get("/api/loopbacks/next")
def next_loopback(state: StateDep, service_id: str = Query(default="", max_length=100)) -> dict[str, Any]:
    service_id = tracing.clean_text(service_id, 100)
    ip = state.repo.peek_loopback(service_id, *loopback_range(state))
    return {"ip": ip, "cidr": f"{ip}/32", "assigned": state.repo.loopback_for_service(service_id) == ip}
