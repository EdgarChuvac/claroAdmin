"""Plantillas por tipo de servicio y catálogo de centrales (archivos en ``config/``)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_SERVICE = "INTERNET"


class ServiceTemplate(BaseModel):
    label: str
    linea1: str
    prefijo_linea2: str
    banner: str
    item_principal: str = "{tipo} LOCAL {velocidad}"
    items_adicionales: list[str] = Field(default_factory=list)
    observaciones: str = ""
    vrf_name: str = ""
    vrf_desc: str = ""
    rd: str = ""
    import_policy: str = ""
    export_policy: str = ""
    apply_label_per_instance: bool = True
    traffic_policy: str = ""
    vpn_targets: list[str] = Field(default_factory=list)
    pendiente_validar: bool = False
    ip_publica: bool = False

    def default_items(self, tipo: str, velocidad: str) -> list[str]:
        principal = self.item_principal.format(tipo=tipo, velocidad=velocidad).strip()
        return [f"{item}  (ACEPTADO)" for item in [principal, *self.items_adicionales] if item]


class NetworkDefaults(BaseModel):
    vrf_gestor: str = "GESTOR_RAISECOM"
    vlan_gestor: str = "836"
    red_gestor: str = "10.40.3.0/24"
    gw_gestor: str = "10.40.3.1"
    ip_gestor_raisecom: str = "10.40.3.120"
    equipo_raisecom: str = "RAISECOM RAX711-L"
    equipo_cpe: str = "CISCO C921"
    loopback_id: str = "5"
    loopback_pool_start: str = "10.212.100.1"
    loopback_pool_end: str = "10.212.100.254"
    # PSK del bloque de monitoreo. No se versiona: se toma de MONITOREO_PSK.
    psk_monitoreo: str = Field(default="", exclude=True)


class Medio(BaseModel):
    label: str
    ruta: str


class Equipment(BaseModel):
    no: str = ""
    rol: str = ""
    marca: str = ""
    modelo: str = ""
    hostname: str = ""
    ip_admon: str = ""
    int_in: str = ""
    int_out: str = ""


class Central(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    nombre: str
    isla: str = ""
    demo: bool = False
    equipos: list[Equipment] = Field(default_factory=list)


DEFAULT_MEDIOS = {
    "FIBRA": Medio(label="FIBRA ÓPTICA", ruta="FO"),
    "RADIO": Medio(label="RADIOENLACE", ruta="RADIO"),
    "GPON": Medio(label="G-PON", ruta="G-PON"),
}


@dataclass
class Catalog:
    services: dict[str, ServiceTemplate]
    network_defaults: NetworkDefaults
    centrales: list[Central] = field(default_factory=list)
    medios: dict[str, Medio] = field(default_factory=lambda: dict(DEFAULT_MEDIOS))

    def medio_ruta(self, medio: str) -> str:
        """Texto del tramo de medio en la ruta (FIBRA -> FO). Valores desconocidos se usan tal cual."""
        key = (medio or "").strip().upper()
        found = self.medios.get(key)
        return found.ruta if found else key

    def service(self, tipo: str) -> ServiceTemplate:
        key = (tipo or "").strip().upper()
        for name, template in self.services.items():
            if name.upper() == key:
                return template
        for name, template in self.services.items():
            if name.upper() in key or template.label.upper() == key:
                return template
        return self.services.get(DEFAULT_SERVICE) or next(iter(self.services.values()))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "services": {name: t.model_dump() for name, t in self.services.items()},
            "network_defaults": self.network_defaults.model_dump(),
            "medios": {name: m.model_dump() for name, m in self.medios.items()},
        }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_catalog(config_dir: str | Path) -> Catalog:
    config_dir = Path(config_dir)
    templates = _read_json(config_dir / "service_templates.json")
    services = {name: ServiceTemplate(**data) for name, data in templates["services"].items()}
    if not services:
        raise ValueError("service_templates.json debe definir al menos un servicio.")
    defaults = NetworkDefaults(**templates.get("network_defaults", {}))
    medios = {name.upper(): Medio(**m) for name, m in templates.get("medios", {}).items()} or dict(DEFAULT_MEDIOS)

    centrales: list[Central] = []
    centrales_path = config_dir / "centrales.json"
    if centrales_path.is_file():
        centrales = [Central(**item) for item in _read_json(centrales_path).get("centrales", [])]
    return Catalog(services=services, network_defaults=defaults, centrales=centrales, medios=medios)


@lru_cache
def default_catalog() -> Catalog:
    return load_catalog(Path(__file__).resolve().parents[2] / "config")
