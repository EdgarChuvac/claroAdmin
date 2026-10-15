"""Carga de la topología (islas y chasis) desde un archivo o desde las colecciones antiguas.

Modelo vigente en Firestore:

* ``islas/{slug}``: ``nombre``, ``region``, ``activo``.
* ``chasis/{id}``: ``nombre``, ``isla_id`` (→ ``islas``), ``region``, ``id_fisico``, ``slots``, ``puertos``…

Estructura anterior (solo lectura, para migrar): ``ISLAS`` con ``NOMBRE``, ``region`` y
``chasis_diponibles`` (ID o lista de IDs de ``EQUIPO_CHASIS``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..repositories.inventory import InventoryRepository
from .catalog import Catalog

LEGACY_ISLAS = "ISLAS"
LEGACY_CHASIS = "EQUIPO_CHASIS"


class IslaSeed(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    region: str
    activo: bool = True


class ChasisSeed(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    isla: str
    nombre: str = ""
    id_fisico: str = ""
    marca: str = ""
    modelo: str = ""
    hostname: str = ""
    ip_admon: str = ""
    slots: list[str] = Field(default_factory=list)
    puertos: list[str] = Field(default_factory=list)
    activo: bool = True


class TopologySeed(BaseModel):
    islas: list[IslaSeed] = Field(default_factory=list)
    chasis: list[ChasisSeed] = Field(default_factory=list)


def load_topology_file(path: str | Path) -> TopologySeed:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    return TopologySeed(**{k: v for k, v in data.items() if not k.startswith("_")})


def _legacy_list(value: Any) -> list[str]:
    """``"[1,3,5]"``, ``"1"``, ``[1, 2]`` o ``None`` -> ``["1", "3", "5"]``."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v for v in re.split(r"[\s,;\[\]]+", str(value)) if v]


def read_legacy_topology(repo: InventoryRepository) -> tuple[TopologySeed, list[str]]:
    """Convierte ``ISLAS`` + ``EQUIPO_CHASIS`` al modelo nuevo. Devuelve también advertencias."""
    warnings: list[str] = []
    islas: dict[str, IslaSeed] = {}
    chasis_isla: dict[str, str] = {}
    for snap in repo.col(LEGACY_ISLAS).stream():
        data = snap.to_dict() or {}
        nombre = str(data.get("NOMBRE") or "").strip()
        region = str(data.get("region") or "").strip().upper()
        if not nombre or not region:
            warnings.append(f"{LEGACY_ISLAS}/{snap.id}: sin NOMBRE o region; se omite.")
            continue
        key = nombre.upper()
        if key in islas and islas[key].region != region:
            warnings.append(f"La isla {nombre} aparece en {islas[key].region} y {region}; se conserva la primera.")
            continue
        islas[key] = IslaSeed(nombre=nombre, region=region)
        for chasis_id in _legacy_list(data.get("chasis_diponibles")):
            if chasis_id in chasis_isla and chasis_isla[chasis_id] != key:
                warnings.append(f"El chasis {chasis_id} está en {chasis_isla[chasis_id]} y {key}; se conserva el primero.")
                continue
            chasis_isla[chasis_id] = key
    chasis: list[ChasisSeed] = []
    for chasis_id, isla in sorted(chasis_isla.items()):
        snap = repo.col(LEGACY_CHASIS).document(chasis_id).get()
        if not snap.exists:
            warnings.append(f"{LEGACY_CHASIS}/{chasis_id} no existe; se omite.")
            continue
        data = snap.to_dict() or {}
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", chasis_id).strip("-")[:64] or "CHASIS"
        chasis.append(ChasisSeed(
            id=safe_id, isla=isla, nombre=str(data.get("nombre") or chasis_id),
            id_fisico=str(data.get("id_fisico") or ""),
            marca=str(data.get("marca") or ""), modelo=str(data.get("modelo") or ""),
            hostname=str(data.get("hostname") or ""), ip_admon=str(data.get("ip_admon") or ""),
            slots=_legacy_list(data.get("slot") or data.get("slots")),
            puertos=_legacy_list(data.get("puerto") or data.get("puertos")),
        ))
    return TopologySeed(islas=list(islas.values()), chasis=chasis), warnings


def apply_topology(repo: InventoryRepository, catalog: Catalog, seed: TopologySeed, operator: str,
                   operation_id: str) -> dict[str, int]:
    """Crea o actualiza islas y chasis (idempotente: se puede ejecutar varias veces)."""
    for isla in seed.islas:
        repo.upsert_isla(isla.nombre, catalog.region(isla.region), operator, operation_id, isla.activo)
    for ch in seed.chasis:
        repo.upsert_chasis(ch.id, ch.isla, ch.model_dump(exclude={"id", "isla"}), operator, operation_id)
    return {"islas": len(seed.islas), "chasis": len(seed.chasis)}
