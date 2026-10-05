"""Reserva y liberación de IPs."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from ...core import tracing
from ...schemas.requests import (
    ReleaseRequest,
    ReservationRequest,
)
from ..dependencies import (
    OperatorDep,
    StateDep,
    serialize,
)

logger = logging.getLogger("claro.api")
router = APIRouter()


@router.post("/api/reservations")
def reserve_ips(req: ReservationRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    tracing.audit("ip.reserve", service_id=req.service_id, ips=req.ips, purpose=req.purpose)
    reserved = state.repo.reserve(req.ips, req.service_id, operator,
                                  tracing.current_operation_id(), req.purpose)
    logger.info("IPs reservadas", extra={"ips": req.ips, "service_id": req.service_id})
    return {
        "message": f"{len(reserved)} IP(s) reservada(s) para el servicio {req.service_id}.",
        "reserved": serialize(reserved),
        "operation_id": tracing.current_operation_id(),
    }

@router.post("/api/reservations/release")
def release_ips(req: ReleaseRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    tracing.audit("ip.release", service_id=req.service_id, ips=req.ips, reason=req.reason)
    released = state.repo.release(req.ips, req.service_id, operator,
                                  tracing.current_operation_id(), req.reason)
    logger.info("IPs liberadas", extra={"ips": req.ips, "service_id": req.service_id})
    return {
        "message": f"{len(released)} IP(s) liberada(s).",
        "released": released,
        "operation_id": tracing.current_operation_id(),
    }
