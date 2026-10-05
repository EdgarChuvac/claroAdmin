"""Modelos de entrada de la API (validación con Pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core import tracing


def validate_service_id(value: str) -> str:
    clean_value = tracing.clean_text(value, 100)
    if not clean_value:
        raise ValueError("El ID de servicio no puede estar vacío.")
    if clean_value.startswith(("=", "+", "-", "@")):
        raise ValueError("El ID de servicio no puede iniciar con un operador de fórmula.")
    return clean_value

class ReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ips: list[str] = Field(min_length=1, max_length=64)
    service_id: str = Field(min_length=1, max_length=100)
    purpose: Literal["WAN", "LAN", "ADICIONAL"] = "WAN"

    @field_validator("service_id")
    @classmethod
    def _check_service(cls, value: str) -> str:
        return validate_service_id(value)

class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ips: list[str] = Field(min_length=1, max_length=64)
    service_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("service_id")
    @classmethod
    def _check_service(cls, value: str) -> str:
        return validate_service_id(value)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        value = tracing.clean_text(value, 300)
        if len(value) < 3:
            raise ValueError("Indique el motivo de la liberación.")
        return value

class EquipmentData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no: str = ""
    rol: str = ""
    marca: str = ""
    modelo: str = ""
    hostname: str = ""
    ip_admon: str = ""
    int_in: str = ""
    int_out: str = ""

class FormatData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str = "INTERNET"
    id_servicio: str = ""
    cliente: str = ""
    disenador: str = ""
    tel_disenador: str = ""
    fecha: str = ""
    factibilidad_bloque: str = ""
    sin_factibilidad: bool = False
    contacto_tec: str = ""
    ejecutivo: str = ""
    consultor: str = ""
    direccion: str = ""
    coordenadas: str = ""
    medio: str = "FIBRA"
    velocidad: str = ""
    ips_count: str = "1"
    equipo_cpe: str = ""
    factibilidad: str = ""
    observaciones: str = ""
    items_aceptados: list[str] = Field(default_factory=list)
    vrf_name: str | None = None
    vrf_desc: str | None = None
    isla: str = ""
    red_wan: str = ""
    rd: str | None = None
    vlan_num: str = ""
    gw_wan: str = ""
    desc_vlan: str = ""
    lan: str = ""
    lan_obs: str = ""
    ip_wan: str = ""
    ips_adicionales: list[str] = Field(default_factory=list, max_length=64)
    loopback: str = ""
    loopback_auto: bool = False
    ip_publica: str = ""
    loopback_id: str = ""
    psk: str = ""
    equipos_claro: list[EquipmentData] = Field(default_factory=list, max_length=30)
    equipo_raisecom: str = ""
    enlace_medio: str = ""
    obs_medio: str = ""
    vrf_gestor: str = ""
    vlan_gestor: str = ""
    red_gestor: str = ""
    gw_gestor: str = ""
    ip_gestor_raisecom: str = ""
    ruta_manual: str = ""
    vpn_targets: list[str] | str | None = None

class GenerateFormatRequest(BaseModel):
    data: FormatData

class AltaRequest(BaseModel):
    data: FormatData

    @field_validator("data")
    @classmethod
    def _require_service(cls, value: FormatData) -> FormatData:
        validate_service_id(value.id_servicio)
        if not value.cliente.strip():
            raise ValueError("El nombre del cliente es obligatorio para registrar el alta.")
        if not value.factibilidad_bloque.strip() and not value.sin_factibilidad:
            raise ValueError("Cargue la factibilidad o marque «Sin factibilidad» antes de registrar el alta.")
        return value

class SheetIslaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isla: str = Field(min_length=1, max_length=60)

class VlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isla: str = Field(default="", max_length=60)
    vlan: str = Field(min_length=1, max_length=4)
    rd: str = Field(default="", max_length=60)
    vrf_name: str = Field(default="", max_length=80)
    vrf_desc: str = Field(default="", max_length=120)
    vlan_desc: str = Field(default="", max_length=120)
