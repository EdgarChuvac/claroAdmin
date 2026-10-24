"""Vista previa, registro y consulta de altas; baja de servicios."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from ...core import tracing
from ...core.errors import InventoryError
from ...repositories.inventory import ALTA_ACTIVA, isla_doc_id
from ...schemas.requests import (
    AltaRequest,
    FormatData,
    GenerateFormatRequest,
    ServiceBajaRequest,
    validate_service_id,
)
from ...services.format_generator import generate_format_text
from ..dependencies import (
    AppState,
    OperatorDep,
    StateDep,
    loopback_range,
    serialize,
    service_id_param,
)

logger = logging.getLogger("claro.api")
router = APIRouter()


def _alta_summary(doc: dict[str, Any]) -> dict[str, Any]:
    summary = {k: doc.get(k) for k in (
        "alta_id", "service_id", "cliente", "tipo_servicio", "ip_wan", "region", "isla", "chasis_id",
        "operator", "operation_id", "created_at",
    )}
    summary["estado"] = doc.get("estado") or ALTA_ACTIVA
    return summary

def _resolve_topology(data: dict[str, Any], form: FormatData, state: AppState) -> None:
    """Valida medio, región y chasis y deja en ``data`` lo que imprime el formato.

    El nombre y el ID físico del chasis se toman de Firestore, no del navegador.
    """
    medio = (form.medio or "").strip().upper()
    if medio not in state.catalog.medios:
        raise InventoryError(f"Medio de transmisión desconocido: {form.medio or '(vacío)'}.")
    data["medio"] = medio
    if form.region.strip():
        try:
            data["region"] = state.catalog.region(form.region)
        except ValueError as exc:
            raise InventoryError(str(exc)) from exc
    for key in ("chasis_nombre", "chasis_id_fisico"):
        data.pop(key, None)
    chasis_id = form.chasis_id.strip()
    if not chasis_id:
        if form.chasis_slot.strip() or form.chasis_puerto.strip():
            raise InventoryError("Se recibieron slot y puerto sin un ID de chasis. Vuelva a seleccionar el chasis.")
        for key in ("chasis_id", "chasis_slot", "chasis_puerto"):
            data.pop(key, None)
        return
    if not state.catalog.medios[medio].usa_chasis:
        raise InventoryError(f"El medio {state.catalog.medios[medio].label} no usa chasis.")
    chasis = state.repo.get_chasis(chasis_id)
    if form.isla.strip() and chasis.get("isla_id") != isla_doc_id(form.isla):
        raise InventoryError(f"El chasis {chasis.get('nombre') or chasis_id} no pertenece a la isla {form.isla}.")
    for field, options in (("chasis_slot", chasis.get("slots") or []), ("chasis_puerto", chasis.get("puertos") or [])):
        value = getattr(form, field).strip()
        valid_options = {str(option).strip() for option in options}
        if value and valid_options and value not in valid_options:
            label = "slot" if field == "chasis_slot" else "puerto"
            raise InventoryError(f"El {label} {value} no existe en el chasis {chasis.get('nombre') or chasis_id}.")
        data[field] = value
    data["chasis_id"] = chasis_id
    data["chasis_nombre"] = chasis.get("nombre") or chasis_id
    data["chasis_id_fisico"] = chasis.get("id_fisico", "")


def _resolve_vlan_config(data: dict[str, Any], form: FormatData, state: AppState) -> None:
    """Obtiene el bloque guardado para el número de VLAN, sin depender de la isla."""
    data["vlan_config"] = state.repo.get_vlan_config(form.vlan_num, form.isla)


def _resolve_equipos_claro(data: dict[str, Any], form: FormatData, state: AppState) -> None:
    """Carga desde Firebase la ruta G-PON o la ruta asociada al chasis."""
    if form.medio.strip().upper() == "GPON":
        route_id = form.gpon_route_id.strip()
        if not route_id:
            raise InventoryError("Seleccione una ruta G-PON de la isla.")
        equipos = state.repo.list_gpon_route_equipment(form.isla, route_id)
        if not equipos:
            raise InventoryError(f"La ruta G-PON {route_id} no tiene equipos cargados.")
    else:
        equipos = state.repo.list_equipos_ruta_chasis(form.chasis_id) if form.chasis_id else []
        if form.chasis_id and not equipos:
            raise InventoryError(f"El chasis {form.chasis_id} no tiene equipos configurados en equipos_ruta.")
    data["equipos_claro"] = equipos


@router.post("/api/generate-format")
def generate_format(req: GenerateFormatRequest, state: StateDep) -> dict[str, str]:
    """Vista previa: genera el texto sin registrarlo (la loopback se muestra sin reservarse)."""
    data = req.data.model_dump(exclude_none=True, exclude_unset=True)
    _resolve_topology(data, req.data, state)
    _resolve_vlan_config(data, req.data, state)
    _resolve_equipos_claro(data, req.data, state)
    if req.data.loopback_auto:
        data["loopback"] = state.repo.peek_loopback(req.data.id_servicio.strip(), *loopback_range(state))
    else:
        data.pop("loopback", None)
    return {"formatted_text": generate_format_text(data, state.catalog)}

@router.post("/api/altas")
def create_alta(req: AltaRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    """Genera el formato de alta y lo registra en ``altas``.

    Loopback, datos de la VLAN y alta se escriben en una sola transacción.
    """
    data = req.data.model_dump(exclude_none=True, exclude_unset=True)
    service_id = validate_service_id(req.data.id_servicio)
    tracing.audit("alta.create", service_id=service_id, cliente=req.data.cliente)
    data.pop("loopback", None)
    _resolve_topology(data, req.data, state)
    if data.get("chasis_id") and (not req.data.chasis_slot.strip() or not req.data.chasis_puerto.strip()):
        raise InventoryError("Seleccione el slot y el puerto del chasis antes de registrar el alta.")
    _resolve_vlan_config(data, req.data, state)
    _resolve_equipos_claro(data, req.data, state)
    vlan = None
    if req.data.isla and req.data.vlan_num.isdigit() and any(
        (req.data.rd, req.data.vrf_name, req.data.vrf_desc, req.data.desc_vlan, data.get("vlan_config"))
    ):
        # Lo que se capturó para la VLAN queda guardado para autocompletar la siguiente alta.
        vlan = (req.data.isla, req.data.vlan_num, {
            "rd": req.data.rd, "vrf_name": req.data.vrf_name,
            "vrf_desc": req.data.vrf_desc, "vlan_desc": req.data.desc_vlan,
            "config": data.get("vlan_config", ""),
        })
    record = {
        "service_id": service_id,
        "cliente": req.data.cliente.strip(),
        "tipo_servicio": req.data.titulo,
        "ip_wan": req.data.ip_wan,
        "red_wan": req.data.red_wan,
        "region": data.get("region", ""),
        "isla": req.data.isla,
        "vlan": req.data.vlan_num,
        "medio": data["medio"],
        "chasis_id": data.get("chasis_id", ""),
        "chasis_slot": req.data.chasis_slot.strip(),
        "chasis_puerto": req.data.chasis_puerto.strip(),
        "operator": operator,
        "operation_id": tracing.current_operation_id(),
        # La PSK solo queda en el texto del alta (necesario para entregarlo), no en form_data.
        "form_data": {k: v for k, v in data.items() if k != "psk"},
    }

    def render(loopback: str | None) -> str:
        return generate_format_text({**data, "loopback": loopback} if loopback else data, state.catalog)

    doc, duplicate = state.repo.register_alta(
        record, render,
        loopback_pool=loopback_range(state) if req.data.loopback_auto else None,
        vlan=vlan,
    )
    tracing.audit("alta.create", service_id=service_id, alta_id=doc["alta_id"], duplicate=duplicate,
                  loopback=doc.get("loopback"))
    logger.info("Alta registrada", extra={"alta_id": doc["alta_id"], "duplicate": duplicate})
    return {
        "alta_id": doc["alta_id"],
        "duplicate": duplicate,
        "created_at": serialize(doc["created_at"]),
        "loopback": doc.get("loopback"),
        "formatted_text": doc["formatted_text"],
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

@router.post("/api/altas/{alta_id}/baja")
def decommission_alta(alta_id: str, req: ServiceBajaRequest, state: StateDep,
                      operator: OperatorDep) -> dict[str, Any]:
    alta_id = tracing.clean_text(alta_id, 40)
    tracing.audit("alta.baja", alta_id=alta_id, reason=req.reason)
    result = state.repo.decommission_alta(alta_id, operator, tracing.current_operation_id(), req.reason)
    tracing.audit("alta.baja", **result)
    return {"message": f"Alta {alta_id} dada de baja; posición del chasis liberada.",
            **result, "operation_id": tracing.current_operation_id()}

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
        "loopback": state.repo.loopback_for_service(service_id),
        "altas": serialize([_alta_summary(a) for a in state.repo.list_altas(service_id, 20)]),
    }

@router.post("/api/services/{service_id}/baja")
def decommission_service(service_id: str, req: ServiceBajaRequest, state: StateDep,
                         operator: OperatorDep) -> dict[str, Any]:
    """Baja del servicio: libera IPs y loopback y marca sus altas como BAJA (una transacción)."""
    service_id = service_id_param(service_id)
    tracing.audit("service.baja", service_id=service_id, reason=req.reason)
    result = state.repo.decommission_service(service_id, operator, tracing.current_operation_id(), req.reason)
    tracing.audit("service.baja", service_id=service_id, ips=result["ips"], loopbacks=result["loopbacks"],
                  altas=result["altas"])
    logger.info("Servicio dado de baja", extra={"service_id": service_id})
    return {
        "message": (f"Servicio {service_id} dado de baja: {len(result['ips'])} IP(s), "
                    f"{len(result['loopbacks'])} loopback(s) y {len(result['altas'])} alta(s)."),
        **result,
        "operation_id": tracing.current_operation_id(),
    }
