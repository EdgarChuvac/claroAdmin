"""Vista previa, registro y consulta de altas."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from ...core import tracing
from ...schemas.requests import (
    AltaRequest,
    GenerateFormatRequest,
    validate_service_id,
)
from ...services.format_generator import generate_format_text
from ..dependencies import (
    OperatorDep,
    StateDep,
    loopback_range,
    serialize,
    service_id_param,
)

logger = logging.getLogger("claro.api")
router = APIRouter()


def _alta_summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: doc.get(k) for k in (
        "alta_id", "service_id", "cliente", "tipo_servicio", "ip_wan", "operator",
        "operation_id", "created_at",
    )}

@router.post("/api/generate-format")
def generate_format(req: GenerateFormatRequest, state: StateDep) -> dict[str, str]:
    """Vista previa: genera el texto sin registrarlo (la loopback se muestra sin reservarse)."""
    data = req.data.model_dump(exclude_none=True, exclude_unset=True)
    if req.data.loopback_auto:
        data["loopback"] = state.repo.peek_loopback(req.data.id_servicio.strip(), *loopback_range(state))
    else:
        data.pop("loopback", None)
    return {"formatted_text": generate_format_text(data, state.catalog)}

@router.post("/api/altas")
def create_alta(req: AltaRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    """Genera el formato de alta y lo registra en la colección ``altas``."""
    data = req.data.model_dump(exclude_none=True, exclude_unset=True)
    service_id = validate_service_id(req.data.id_servicio)
    tracing.audit("alta.create", service_id=service_id, cliente=req.data.cliente)
    data.pop("loopback", None)
    if req.data.loopback_auto:
        data["loopback"] = state.repo.assign_loopback(
            service_id, operator, tracing.current_operation_id(), *loopback_range(state)
        )
        tracing.audit("alta.create", service_id=service_id, loopback=data["loopback"])
    if req.data.isla and req.data.vlan_num.isdigit() and any(
        (req.data.rd, req.data.vrf_name, req.data.vrf_desc, req.data.desc_vlan)
    ):
        # Lo que se capturó para la VLAN queda guardado para autocompletar la siguiente alta.
        state.repo.upsert_vlan(req.data.isla, req.data.vlan_num, {
            "rd": req.data.rd, "vrf_name": req.data.vrf_name,
            "vrf_desc": req.data.vrf_desc, "vlan_desc": req.data.desc_vlan,
        }, operator, tracing.current_operation_id())
    text = generate_format_text(data, state.catalog)
    record = {
        "service_id": service_id,
        "cliente": req.data.cliente.strip(),
        "tipo_servicio": req.data.titulo,
        "ip_wan": req.data.ip_wan,
        "red_wan": req.data.red_wan,
        "isla": req.data.isla,
        "vlan": req.data.vlan_num,
        "loopback": data.get("loopback"),
        "operator": operator,
        "operation_id": tracing.current_operation_id(),
        "formatted_text": text,
        # La PSK solo queda en el texto del alta (necesario para entregarlo), no en form_data.
        "form_data": {k: v for k, v in data.items() if k != "psk"},
    }
    doc, duplicate = state.repo.create_alta(record)
    tracing.audit("alta.create", service_id=service_id, alta_id=doc["alta_id"], duplicate=duplicate)
    logger.info("Alta registrada", extra={"alta_id": doc["alta_id"], "duplicate": duplicate})
    return {
        "alta_id": doc["alta_id"],
        "duplicate": duplicate,
        "created_at": serialize(doc["created_at"]),
        "formatted_text": text,
        "operation_id": tracing.current_operation_id(),
    }

@router.get("/api/altas")
def list_altas(
    state: StateDep,
    service_id: str = Query(default="", max_length=100),
    limit: int = Query(default=30, ge=1, le=200),
) -> dict[str, Any]:
    service_id = tracing.clean_text(service_id, 100)
    return {"altas": serialize([_alta_summary(a) for a in state.repo.list_altas(service_id, limit)])}

@router.get("/api/altas/{alta_id}")
def get_alta(alta_id: str, state: StateDep) -> dict[str, Any]:
    doc = state.repo.get_alta(tracing.clean_text(alta_id, 40))
    return serialize({k: v for k, v in doc.items() if k != "content_hash"})

@router.get("/api/services/{service_id}")
def get_service(service_id: str, state: StateDep) -> dict[str, Any]:
    service_id = service_id_param(service_id)
    return {
        "service_id": service_id,
        "ips": serialize(state.repo.search_service(service_id)),
        "altas": serialize([_alta_summary(a) for a in state.repo.list_altas(service_id, 20)]),
    }
