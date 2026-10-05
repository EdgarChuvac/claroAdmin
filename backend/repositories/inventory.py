"""Acceso a datos en Cloud Firestore.

Colecciones (todas con el prefijo ``FIRESTORE_COLLECTION_PREFIX``):

``inventory_sheets/{red_base}``
    Resumen por segmento /24 (equivale a una pestaña del Excel).
``ip_segments/{red}_{cidr}``
    Subred detectada: red, gateway, broadcast, VLAN y contadores.
``ip_addresses/{ip}``
    Una IP utilizable: ``DISPONIBLE``, ``OCUPADA`` o ``GATEWAY``.
``inventory_imports/{id}``
    Bitácora de cada importación de Excel.
``altas/{id}``
    Cada formato de alta generado y registrado.
``alta_hashes/{sha256}``
    Índice de unicidad del texto de cada alta.
``operations/{operation_id}``
    Auditoría de operaciones (ver ``backend.tracing``).
``centrales/{id}``
    Catálogo de centrales y rutas de equipos.
``vlans/{isla}_{vlan}``
    Datos de red por VLAN (RD, VRF y descripciones) para autocompletar el alta.
``loopbacks/{ip}``
    Loopbacks /32 asignadas automáticamente (pool 10.212.100.1-254 por defecto).
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address
from typing import Any, Iterable

from ..core.errors import ConflictError, InventoryError, NotFoundError
from ..db.firebase_client import FirestoreHandle
from ..services.excel_parser import IPBlock

logger = logging.getLogger(__name__)

STATUS_FREE = "DISPONIBLE"
STATUS_USED = "OCUPADA"
STATUS_GATEWAY = "GATEWAY"

MAX_IPS_PER_RESERVATION = 64
BATCH_LIMIT = 450  # margen bajo el límite de 500 operaciones por lote


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ip_sort_key(value: str) -> int:
    try:
        return int(IPv4Address(value))
    except ValueError:
        return 0


def normalize_ips(ips: Iterable[str]) -> list[str]:
    result: list[str] = []
    for raw in ips:
        try:
            ip = str(IPv4Address(str(raw).strip()))
        except ValueError as exc:
            raise InventoryError(f"IP inválida: {raw}") from exc
        if ip in result:
            raise InventoryError(f"IP repetida en la solicitud: {ip}")
        result.append(ip)
    if not result:
        raise InventoryError("Debe indicar al menos una IP.")
    if len(result) > MAX_IPS_PER_RESERVATION:
        raise InventoryError(f"Máximo {MAX_IPS_PER_RESERVATION} IPs por operación.")
    return result


def segment_id_for(block: IPBlock) -> str:
    return f"{block.ip_base}.{block.network_octet}_{block.cidr}"


def normalize_isla(value: str | None) -> str:
    return " ".join((value or "").split()).upper()[:60]


def vlan_doc_id(isla: str, vlan: str) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "-", normalize_isla(isla)).strip("-") or "SIN-ISLA"
    return f"{slug}_{vlan}"


def new_readable_id(prefix: str) -> str:
    return f"{prefix}-{utcnow():%Y%m%d}-{secrets.token_hex(4).upper()}"


@dataclass
class ImportResult:
    import_id: str
    mode: str
    sheets: list[str]
    ignored_sheets: list[str]
    segments: int
    ips_written: int
    ips_unchanged: int
    ips_deleted: int
    conflicts: list[dict[str, Any]]
    totals: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "mode": self.mode,
            "sheets": self.sheets,
            "ignored_sheets": self.ignored_sheets,
            "segments": self.segments,
            "ips_written": self.ips_written,
            "ips_unchanged": self.ips_unchanged,
            "ips_deleted": self.ips_deleted,
            "conflicts_count": len(self.conflicts),
            "conflicts": self.conflicts[:200],
            "totals": self.totals,
        }


class InventoryRepository:
    def __init__(self, handle: FirestoreHandle, prefix: str = "", operations_retention_days: int = 365):
        self.handle = handle
        self.client = handle.client
        self.prefix = prefix
        self.operations_retention_days = operations_retention_days

    # ------------------------------------------------------------------
    # utilidades
    # ------------------------------------------------------------------
    def col(self, name: str):
        return self.client.collection(f"{self.prefix}{name}")

    def _where(self, collection: str, field: str, op: str, value: Any):
        return self.col(collection).where(filter=self.handle.field_filter(field, op, value))

    def _commit_in_batches(self, ops: list[tuple[str, Any, dict[str, Any] | None]]) -> None:
        for start in range(0, len(ops), BATCH_LIMIT):
            batch = self.client.batch()
            for kind, ref, data in ops[start:start + BATCH_LIMIT]:
                if kind == "set":
                    batch.set(ref, data)
                elif kind == "merge":
                    batch.set(ref, data, merge=True)
                else:
                    batch.delete(ref)
            batch.commit()

    def _run_transaction(self, func):
        """Ejecuta ``func`` en una transacción (reintenta ante contención)."""
        try:
            return self.handle.transactional(func)(self.client.transaction(max_attempts=10))
        except InventoryError:
            raise
        except Exception as exc:
            # Aborted / "Failed to commit transaction in N attempts" del SDK.
            if "attempt" in str(exc).lower() or exc.__class__.__name__ == "Aborted":
                raise ConflictError("Otra operación modificó estas IPs al mismo tiempo. Intente de nuevo.") from exc
            raise

    def ping(self) -> bool:
        list(self.col("inventory_sheets").limit(1).stream())
        return True

    # ------------------------------------------------------------------
    # Importación de inventario
    # ------------------------------------------------------------------
    @staticmethod
    def _ip_docs_for_block(block: IPBlock, segment_id: str, import_id: str, now: datetime) -> dict[str, dict[str, Any]]:
        docs: dict[str, dict[str, Any]] = {}
        base = {
            "sheet": block.sheet_name,
            "segment_id": segment_id,
            "import_id": import_id,
            "updated_at": now,
        }
        if block.gateway_ip and block.gateway_octet is not None:
            docs[block.gateway_ip] = {
                **base, "ip": block.gateway_ip, "octet": block.gateway_octet,
                "status": STATUS_GATEWAY, "service_id": None,
            }
        for item in block.available_ips:
            docs[item["ip"]] = {
                **base, "ip": item["ip"], "octet": item["octet"],
                "status": STATUS_FREE, "service_id": None,
            }
        for item in block.assigned_ips:
            docs[item["ip"]] = {
                **base, "ip": item["ip"], "octet": item["octet"],
                "status": STATUS_USED, "service_id": item["id"],
                "assigned_by": "importación excel", "assigned_at": now,
                "assigned_operation_id": None,
            }
        return docs

    @staticmethod
    def _segment_doc(block: IPBlock, segment_id: str, import_id: str, now: datetime) -> dict[str, Any]:
        return {
            "segment_id": segment_id,
            "sheet": block.sheet_name,
            "network_ip": block.network_ip,
            "network_octet": block.network_octet,
            "broadcast_ip": block.broadcast_ip,
            "broadcast_octet": block.broadcast_octet,
            "gateway_ip": block.gateway_ip,
            "gateway_octet": block.gateway_octet,
            "cidr": block.cidr,
            "size": block.size,
            "vlan": block.vlan,
            "vlan_raw": block.vlan_raw,
            "import_id": import_id,
            "updated_at": now,
        }

    def import_inventory(
        self,
        blocks_by_sheet: dict[str, list[IPBlock]],
        *,
        mode: str,
        filename: str,
        operator: str,
        operation_id: str,
        ignored_sheets: list[str],
        isla: str = "",
    ) -> ImportResult:
        """Importa el inventario del Excel.

        * ``replace``: operación de mantenimiento; borra y recrea las hojas incluidas.
        * ``merge``: cada IP se escribe en una transacción que vuelve a verificar
          que nadie la modificó desde la lectura; las IPs ocupadas en Firestore
          nunca se sobrescriben. Al final los contadores se recalculan dentro de
          una transacción a partir del estado real.
        """
        if mode not in {"merge", "replace"}:
            raise InventoryError("Modo de importación inválido (use 'merge' o 'replace').")
        if not any(blocks_by_sheet.values()):
            raise InventoryError(
                "El Excel no contiene subredes reconocibles. Revise que las hojas se llamen "
                "como la red base (p. ej. 10.20.38.0) y que cada bloque cierre con BROADCAST."
            )

        now = utcnow()
        import_id = new_readable_id("IMP")
        conflicts: list[dict[str, Any]] = []
        written = unchanged = deleted = 0
        totals = {"segments": 0, STATUS_FREE: 0, STATUS_USED: 0, STATUS_GATEWAY: 0}
        sheets = [s for s, b in blocks_by_sheet.items() if b]

        isla = normalize_isla(isla)
        for sheet in sheets:
            blocks = blocks_by_sheet[sheet]
            existing_sheet = self.col("inventory_sheets").document(sheet).get()
            previous_isla = (existing_sheet.to_dict() or {}).get("isla", "") if existing_sheet.exists else ""
            sheet_isla = isla or previous_isla
            new_segments: dict[str, dict[str, Any]] = {}
            new_ips: dict[str, dict[str, Any]] = {}
            for block in blocks:
                seg_id = segment_id_for(block)
                if seg_id in new_segments:
                    raise InventoryError(f"Subred duplicada en la hoja {sheet}: {block.network_ip}")
                new_segments[seg_id] = {**self._segment_doc(block, seg_id, import_id, now), "isla": sheet_isla}
                for ip, doc in self._ip_docs_for_block(block, seg_id, import_id, now).items():
                    if ip in new_ips:
                        raise InventoryError(
                            f"La IP {ip} aparece en más de una subred de la hoja {sheet}. "
                            "Corrija los rangos superpuestos en el Excel."
                        )
                    new_ips[ip] = doc

            existing_ips = {
                snap.id: snap.to_dict()
                for snap in self._where("ip_addresses", "sheet", "==", sheet).stream()
            }
            existing_segments = {
                snap.id: snap.to_dict()
                for snap in self._where("ip_segments", "sheet", "==", sheet).stream()
            }

            ops: list[tuple[str, Any, dict[str, Any] | None]] = []
            if mode == "replace":
                for ip in existing_ips.keys() - new_ips.keys():
                    ops.append(("delete", self.col("ip_addresses").document(ip), None))
                    deleted += 1
                for seg in existing_segments.keys() - new_segments.keys():
                    ops.append(("delete", self.col("ip_segments").document(seg), None))
                for ip, doc in new_ips.items():
                    ops.append(("set", self.col("ip_addresses").document(ip), doc))
                    written += 1
                for seg_id, seg in new_segments.items():
                    ops.append(("set", self.col("ip_segments").document(seg_id), seg))
                self._commit_in_batches(ops)
            else:
                # Subredes existentes reemplazadas por una nueva subdivisión del rango.
                new_ranges = [(s["network_octet"], s["broadcast_octet"]) for s in new_segments.values()]
                stale_segments = {
                    seg_id for seg_id, seg in existing_segments.items()
                    if seg_id not in new_segments and any(
                        seg["network_octet"] <= hi and lo <= seg["broadcast_octet"] for lo, hi in new_ranges
                    )
                }
                guarded: list[tuple[str, dict[str, Any] | None, dict[str, Any]]] = []
                for ip, doc in new_ips.items():
                    current = existing_ips.get(ip)
                    if current and current.get("status") == STATUS_USED:
                        if doc["status"] != STATUS_USED or doc.get("service_id") != current.get("service_id"):
                            conflicts.append({
                                "ip": ip,
                                "firestore": current.get("service_id"),
                                "excel": doc.get("service_id") or doc["status"],
                                "resolucion": "se conserva el valor de Firestore",
                            })
                        if current.get("segment_id") != doc["segment_id"]:
                            # conservar la reserva y su trazabilidad, solo mover de subred
                            guarded.append((ip, current, {**current, "segment_id": doc["segment_id"], "updated_at": now}))
                        else:
                            unchanged += 1
                        continue
                    if current and all(current.get(k) == doc.get(k) for k in ("status", "service_id", "segment_id")):
                        unchanged += 1
                        continue
                    guarded.append((ip, current, doc))

                ops = [("set", self.col("ip_segments").document(seg_id), seg) for seg_id, seg in new_segments.items()]
                self._commit_in_batches(ops)
                w, late_conflicts = self._guarded_ip_writes(guarded)
                written += w
                conflicts.extend(late_conflicts)
                # IPs de subredes reemplazadas que ya no son asignables (ahora son
                # red/broadcast de la nueva subdivisión): se eliminan si están libres.
                still_used: set[str] = set()
                orphan_deletes = []
                for ip, doc in existing_ips.items():
                    if ip in new_ips:
                        continue
                    if doc.get("segment_id") in stale_segments and doc.get("status") != STATUS_USED:
                        orphan_deletes.append(("delete", self.col("ip_addresses").document(ip), None))
                        deleted += 1
                        continue
                    if doc.get("segment_id") in stale_segments:
                        conflicts.append({
                            "ip": ip, "firestore": doc.get("service_id"), "excel": "RED/BROADCAST",
                            "resolucion": "IP ocupada fuera de las nuevas subredes; se conserva la subred anterior",
                        })
                    still_used.add(doc.get("segment_id"))
                self._commit_in_batches(orphan_deletes)
                deletable = [s for s in stale_segments if s not in still_used]
                self._commit_in_batches([("delete", self.col("ip_segments").document(s), None) for s in deletable])

            sheet_counts, segments_count = self._recompute_counters(sheet, import_id, sheet_isla)
            totals["segments"] += segments_count
            for key in sheet_counts:
                totals[key] += sheet_counts[key]

        result = ImportResult(
            import_id=import_id, mode=mode, sheets=sheets, ignored_sheets=ignored_sheets,
            segments=totals["segments"], ips_written=written, ips_unchanged=unchanged,
            ips_deleted=deleted, conflicts=conflicts,
            totals={"disponibles": totals[STATUS_FREE], "ocupadas": totals[STATUS_USED],
                    "gateways": totals[STATUS_GATEWAY]},
        )
        self.col("inventory_imports").document(import_id).set({
            **{k: v for k, v in result.to_dict().items() if k != "conflicts"},
            "conflicts": conflicts[:200],
            "filename": filename,
            "operator": operator,
            "operation_id": operation_id,
            "created_at": now,
        })
        return result

    GUARDED_CHUNK = 150

    def _guarded_ip_writes(
        self, guarded: list[tuple[str, dict[str, Any] | None, dict[str, Any]]]
    ) -> tuple[int, list[dict[str, Any]]]:
        """Escribe IPs solo si siguen como se leyeron (evita pisar reservas concurrentes)."""
        written = 0
        conflicts: list[dict[str, Any]] = []

        def same(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
            if a is None or b is None:
                return a is None and b is None
            return all(a.get(k) == b.get(k) for k in ("status", "service_id"))

        for start in range(0, len(guarded), self.GUARDED_CHUNK):
            chunk = guarded[start:start + self.GUARDED_CHUNK]

            def run(transaction, chunk=chunk):
                refs = [self.col("ip_addresses").document(ip) for ip, _e, _d in chunk]
                snaps = [ref.get(transaction=transaction) for ref in refs]
                local_written = 0
                local_conflicts = []
                for ref, snap, (ip, expected, doc) in zip(refs, snaps, chunk, strict=True):
                    current = snap.to_dict() if snap.exists else None
                    if not same(current, expected):
                        local_conflicts.append({
                            "ip": ip,
                            "firestore": (current or {}).get("service_id") or (current or {}).get("status"),
                            "excel": doc.get("service_id") or doc["status"],
                            "resolucion": "modificada durante la importación; se conserva Firestore",
                        })
                        continue
                    transaction.set(ref, doc)
                    local_written += 1
                return local_written, local_conflicts

            w, c = self._run_transaction(run)
            written += w
            conflicts.extend(c)
        return written, conflicts

    def _recompute_counters(self, sheet: str, import_id: str, isla: str = "") -> tuple[dict[str, int], int]:
        """Recalcula contadores de la hoja y sus subredes a partir del estado real."""

        def run(transaction):
            segments = {
                snap.id: snap.reference
                for snap in self._where("ip_segments", "sheet", "==", sheet).stream(transaction=transaction)
            }
            counts: dict[str, dict[str, int]] = defaultdict(lambda: {STATUS_FREE: 0, STATUS_USED: 0, STATUS_GATEWAY: 0})
            for snap in self._where("ip_addresses", "sheet", "==", sheet).stream(transaction=transaction):
                doc = snap.to_dict()
                if doc.get("status") in counts[doc.get("segment_id", "")]:
                    counts[doc.get("segment_id", "")][doc["status"]] += 1
            sheet_counts = {STATUS_FREE: 0, STATUS_USED: 0, STATUS_GATEWAY: 0}
            for seg_id, ref in segments.items():
                seg_counts = counts[seg_id]
                transaction.update(ref, {
                    "available_count": seg_counts[STATUS_FREE],
                    "assigned_count": seg_counts[STATUS_USED],
                })
                for key in sheet_counts:
                    sheet_counts[key] += seg_counts[key]
            transaction.set(self.col("inventory_sheets").document(sheet), {
                "sheet": sheet,
                "segments_count": len(segments),
                "available_count": sheet_counts[STATUS_FREE],
                "assigned_count": sheet_counts[STATUS_USED],
                "gateway_count": sheet_counts[STATUS_GATEWAY],
                "isla": isla,
                "last_import_id": import_id,
                "updated_at": utcnow(),
            })
            return sheet_counts, len(segments)

        return self._run_transaction(run)

    # ------------------------------------------------------------------
    # Consultas de inventario
    # ------------------------------------------------------------------
    def list_sheets(self) -> list[dict[str, Any]]:
        sheets = [snap.to_dict() for snap in self.col("inventory_sheets").stream()]
        return sorted(sheets, key=lambda s: ip_sort_key(s.get("sheet", "")))

    def get_blocks(self, sheet: str) -> list[dict[str, Any]]:
        if not self.col("inventory_sheets").document(sheet).get().exists:
            raise NotFoundError("La hoja solicitada no existe en el inventario.")
        segments = [snap.to_dict() for snap in self._where("ip_segments", "sheet", "==", sheet).stream()]
        ips_by_segment: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for snap in self._where("ip_addresses", "sheet", "==", sheet).stream():
            doc = snap.to_dict()
            ips_by_segment[doc.get("segment_id", "")].append(doc)

        blocks = []
        for seg in sorted(segments, key=lambda s: s.get("network_octet", 0)):
            ips = sorted(ips_by_segment.get(seg["segment_id"], []), key=lambda d: d.get("octet", 0))
            available = [
                {"octet": d["octet"], "ip": d["ip"], "status": STATUS_FREE}
                for d in ips if d.get("status") == STATUS_FREE
            ]
            assigned = [
                {
                    "octet": d["octet"], "ip": d["ip"], "id": d.get("service_id"),
                    "status": STATUS_USED, "assigned_by": d.get("assigned_by"),
                    "assigned_at": d.get("assigned_at"),
                    "assigned_operation_id": d.get("assigned_operation_id"),
                }
                for d in ips if d.get("status") == STATUS_USED
            ]
            blocks.append({
                "segment_id": seg["segment_id"],
                "sheet_name": seg["sheet"],
                "network_ip": seg["network_ip"],
                "network_octet": seg["network_octet"],
                "broadcast_ip": seg["broadcast_ip"],
                "broadcast_octet": seg["broadcast_octet"],
                "gateway_ip": seg.get("gateway_ip"),
                "gateway_octet": seg.get("gateway_octet"),
                "vlan": seg.get("vlan", ""),
                "vlan_raw": seg.get("vlan_raw", ""),
                "cidr": f"/{seg['cidr']}",
                "size": seg["size"],
                "available_count": len(available),
                "assigned_count": len(assigned),
                "available_ips": available,
                "assigned_ips": assigned,
                "first_available": available[0] if available else None,
            })
        return blocks

    def search_service(self, service_id: str) -> list[dict[str, Any]]:
        ips = [snap.to_dict() for snap in self._where("ip_addresses", "service_id", "==", service_id).stream()]
        return sorted(ips, key=lambda d: ip_sort_key(d.get("ip", "")))

    def inventory_snapshot(self) -> dict[str, dict[str, Any]]:
        """Inventario completo agrupado por hoja (para exportar a Excel)."""
        snapshot: dict[str, dict[str, Any]] = {}
        for sheet in self.list_sheets():
            name = sheet["sheet"]
            segments = sorted(
                (snap.to_dict() for snap in self._where("ip_segments", "sheet", "==", name).stream()),
                key=lambda s: s.get("network_octet", 0),
            )
            ips = {snap.id: snap.to_dict() for snap in self._where("ip_addresses", "sheet", "==", name).stream()}
            snapshot[name] = {"segments": segments, "ips": ips}
        return snapshot

    # ------------------------------------------------------------------
    # Reservas
    # ------------------------------------------------------------------
    def _adjust_counters(self, transaction, segment_deltas: dict[str, int]) -> None:
        """Ajusta contadores de segmentos y hojas dentro de una transacción.

        Firestore exige que todas las lecturas ocurran antes de las escrituras,
        por eso primero se leen todos los documentos y luego se escriben.
        """
        seg_refs = {seg: self.col("ip_segments").document(seg) for seg in segment_deltas}
        seg_snaps = {seg: ref.get(transaction=transaction) for seg, ref in seg_refs.items()}
        sheet_deltas: dict[str, int] = defaultdict(int)
        for seg, snap in seg_snaps.items():
            if snap.exists:
                sheet_deltas[snap.to_dict()["sheet"]] += segment_deltas[seg]
        sheet_refs = {sheet: self.col("inventory_sheets").document(sheet) for sheet in sheet_deltas}
        sheet_snaps = {sheet: ref.get(transaction=transaction) for sheet, ref in sheet_refs.items()}

        for seg, snap in seg_snaps.items():
            if not snap.exists:
                continue
            data = snap.to_dict()
            delta = segment_deltas[seg]
            transaction.update(seg_refs[seg], {
                "available_count": max(0, data.get("available_count", 0) - delta),
                "assigned_count": max(0, data.get("assigned_count", 0) + delta),
            })
        for sheet, snap in sheet_snaps.items():
            if not snap.exists:
                continue
            data = snap.to_dict()
            delta = sheet_deltas[sheet]
            transaction.update(sheet_refs[sheet], {
                "available_count": max(0, data.get("available_count", 0) - delta),
                "assigned_count": max(0, data.get("assigned_count", 0) + delta),
                "updated_at": utcnow(),
            })

    def reserve(self, ips: list[str], service_id: str, operator: str, operation_id: str,
                purpose: str = "WAN") -> list[dict[str, Any]]:
        ips = normalize_ips(ips)
        refs = {ip: self.col("ip_addresses").document(ip) for ip in ips}

        def run(transaction):
            snaps = {ip: ref.get(transaction=transaction) for ip, ref in refs.items()}
            deltas: dict[str, int] = defaultdict(int)
            for ip, snap in snaps.items():
                if not snap.exists:
                    raise NotFoundError(f"La IP {ip} no pertenece al inventario.", ip=ip)
                data = snap.to_dict()
                if data.get("status") != STATUS_FREE:
                    detail = f" (asignada a {data.get('service_id')})" if data.get("service_id") else ""
                    raise ConflictError(f"La IP {ip} ya no está disponible{detail}.", ip=ip)
                deltas[data["segment_id"]] += 1
            # lecturas de contadores antes de cualquier escritura
            now = utcnow()
            pending = []
            for ip, snap in snaps.items():
                data = snap.to_dict()
                pending.append((refs[ip], {
                    "status": STATUS_USED,
                    "service_id": service_id,
                    "purpose": purpose,
                    "assigned_by": operator,
                    "assigned_at": now,
                    "assigned_operation_id": operation_id,
                    "updated_at": now,
                }, data))
            self._adjust_counters_reads_then_writes(transaction, deltas, pending)
            return [{**data, **update, "ip": data["ip"]} for _ref, update, data in pending]

        return self._run_transaction(run)

    def _adjust_counters_reads_then_writes(self, transaction, deltas, pending) -> None:
        # _adjust_counters hace sus lecturas primero; las escrituras de IP van al final.
        self._adjust_counters(transaction, deltas)
        for ref, update, _data in pending:
            transaction.update(ref, update)

    def release(self, ips: list[str], service_id: str, operator: str, operation_id: str,
                reason: str) -> list[dict[str, Any]]:
        ips = normalize_ips(ips)
        refs = {ip: self.col("ip_addresses").document(ip) for ip in ips}

        def run(transaction):
            snaps = {ip: ref.get(transaction=transaction) for ip, ref in refs.items()}
            deltas: dict[str, int] = defaultdict(int)
            for ip, snap in snaps.items():
                if not snap.exists:
                    raise NotFoundError(f"La IP {ip} no pertenece al inventario.", ip=ip)
                data = snap.to_dict()
                if data.get("status") != STATUS_USED:
                    raise ConflictError(f"La IP {ip} no está ocupada.", ip=ip)
                if (data.get("service_id") or "").strip() != service_id:
                    raise ConflictError(
                        f"La IP {ip} pertenece al servicio {data.get('service_id')}, no a {service_id}.", ip=ip
                    )
                deltas[data["segment_id"]] -= 1
            now = utcnow()
            pending = []
            for ip, snap in snaps.items():
                data = snap.to_dict()
                pending.append((refs[ip], {
                    "status": STATUS_FREE,
                    "service_id": None,
                    "purpose": None,
                    "assigned_by": None,
                    "assigned_at": None,
                    "assigned_operation_id": None,
                    "released_by": operator,
                    "released_at": now,
                    "released_operation_id": operation_id,
                    "released_service_id": data.get("service_id"),
                    "release_reason": reason,
                    "updated_at": now,
                }, data))
            self._adjust_counters_reads_then_writes(transaction, deltas, pending)
            return [{"ip": data["ip"], "previous_service_id": data.get("service_id")} for _r, _u, data in pending]

        return self._run_transaction(run)

    # ------------------------------------------------------------------
    # Altas
    # ------------------------------------------------------------------
    def create_alta(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Guarda un alta. Si ya existe una idéntica (mismo texto) la devuelve.

        La unicidad se garantiza con un documento ``alta_hashes/{sha256}`` creado
        en la misma transacción que el alta.
        """
        content_hash = hashlib.sha256(record["formatted_text"].encode("utf-8")).hexdigest()
        hash_ref = self.col("alta_hashes").document(content_hash)

        def run(transaction):
            snap = hash_ref.get(transaction=transaction)
            if snap.exists:
                existing = self.col("altas").document(snap.to_dict()["alta_id"]).get(transaction=transaction)
                if existing.exists:
                    return existing.to_dict(), True
            alta_id = new_readable_id("ALTA")
            doc = {**record, "alta_id": alta_id, "content_hash": content_hash, "created_at": utcnow()}
            transaction.set(self.col("altas").document(alta_id), doc)
            transaction.set(hash_ref, {"alta_id": alta_id, "created_at": doc["created_at"]})
            return doc, False

        return self._run_transaction(run)

    def get_alta(self, alta_id: str) -> dict[str, Any]:
        snap = self.col("altas").document(alta_id).get()
        if not snap.exists:
            raise NotFoundError("Alta no encontrada.")
        return snap.to_dict()

    def list_altas(self, service_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        query = self._where("altas", "service_id", "==", service_id) if service_id else self.col("altas")
        query = query.order_by("created_at", direction=self.handle.descending).limit(limit)
        return [snap.to_dict() for snap in query.stream()]

    # ------------------------------------------------------------------
    # Operaciones (auditoría)
    # ------------------------------------------------------------------
    def save_operation(self, record: dict[str, Any]) -> None:
        created = record.get("created_at") or utcnow()
        record = {**record, "created_at": created,
                  "expires_at": created + timedelta(days=self.operations_retention_days)}
        self.col("operations").document(record["operation_id"]).set(record)

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        snap = self.col("operations").document(operation_id).get()
        if not snap.exists:
            raise NotFoundError("Operación no encontrada.")
        return snap.to_dict()

    def list_operations(self, operator: str = "", service_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if operator:
            query = self._where("operations", "operator", "==", operator)
        elif service_id:
            query = self._where("operations", "service_id", "==", service_id)
        else:
            query = self.col("operations")
        query = query.order_by("created_at", direction=self.handle.descending).limit(limit)
        return [snap.to_dict() for snap in query.stream()]

    # ------------------------------------------------------------------
    # Catálogo de centrales
    # ------------------------------------------------------------------
    def list_centrales(self) -> list[dict[str, Any]]:
        return sorted(
            (snap.to_dict() for snap in self.col("centrales").stream()),
            key=lambda c: c.get("nombre", ""),
        )

    def replace_centrales(self, centrales: list[dict[str, Any]]) -> int:
        existing = {snap.id for snap in self.col("centrales").stream()}
        ops: list[tuple[str, Any, dict[str, Any] | None]] = []
        for central in centrales:
            ops.append(("set", self.col("centrales").document(central["id"]),
                        {**central, "updated_at": utcnow()}))
        for stale in existing - {c["id"] for c in centrales}:
            ops.append(("delete", self.col("centrales").document(stale), None))
        self._commit_in_batches(ops)
        return len(centrales)

    # ------------------------------------------------------------------
    # Islas, segmentos y catálogo de VLANs
    # ------------------------------------------------------------------
    def set_sheet_isla(self, sheet: str, isla: str) -> dict[str, Any]:
        """Asigna la isla/central a un segmento /24 y a todas sus subredes."""
        isla = normalize_isla(isla)
        sheet_ref = self.col("inventory_sheets").document(sheet)
        if not sheet_ref.get().exists:
            raise NotFoundError("La hoja solicitada no existe en el inventario.")
        ops: list[tuple[str, Any, dict[str, Any] | None]] = [("merge", sheet_ref, {"isla": isla, "updated_at": utcnow()})]
        for snap in self._where("ip_segments", "sheet", "==", sheet).stream():
            ops.append(("merge", snap.reference, {"isla": isla}))
        self._commit_in_batches(ops)
        return {"sheet": sheet, "isla": isla, "segments": len(ops) - 1}

    def list_segments(self, isla: str | None = None) -> list[dict[str, Any]]:
        """Subredes (sin el detalle de IPs). ``isla=""`` devuelve las que no tienen isla."""
        if isla:
            snaps = self._where("ip_segments", "isla", "==", normalize_isla(isla)).stream()
            segments = [snap.to_dict() for snap in snaps]
        else:
            segments = [snap.to_dict() for snap in self.col("ip_segments").stream()]
            if isla == "":
                segments = [s for s in segments if not s.get("isla")]
        keys = ("segment_id", "sheet", "isla", "network_ip", "gateway_ip", "cidr", "vlan", "vlan_raw",
                "available_count", "assigned_count")
        return sorted(
            ({k: s.get(k) for k in keys} for s in segments),
            key=lambda s: (ip_sort_key(s.get("sheet") or ""), ip_sort_key((s.get("network_ip") or "").split("/")[0])),
        )

    def list_islas(self) -> list[str]:
        islas = {s.get("isla") for s in self.list_sheets() if s.get("isla")}
        islas |= {c.get("isla") for c in self.list_centrales() if c.get("isla")}
        islas |= {v.get("isla") for v in (snap.to_dict() for snap in self.col("vlans").stream()) if v.get("isla")}
        return sorted(normalize_isla(i) for i in islas)

    def list_vlans(self, isla: str = "") -> list[dict[str, Any]]:
        query = self._where("vlans", "isla", "==", normalize_isla(isla)) if isla else self.col("vlans")
        vlans = [snap.to_dict() for snap in query.stream()]
        return sorted(vlans, key=lambda v: (v.get("isla", ""), int(v["vlan"]) if str(v.get("vlan", "")).isdigit() else 0))

    VLAN_FIELDS = ("rd", "vrf_name", "vrf_desc", "vlan_desc")

    def upsert_vlan(self, isla: str, vlan: str, values: dict[str, str], operator: str,
                    operation_id: str) -> dict[str, Any]:
        """Guarda RD, VRF y descripciones de una VLAN. Los campos vacíos no borran lo guardado."""
        isla = normalize_isla(isla)
        vlan = str(vlan).strip()
        if not vlan.isdigit() or not 1 <= int(vlan) <= 4094:
            raise InventoryError("Número de VLAN inválido (1 a 4094).")
        updates = {k: str(values.get(k) or "").strip() for k in self.VLAN_FIELDS}
        updates = {k: v for k, v in updates.items() if v}
        if not updates:
            raise InventoryError("Indique al menos el RD, la VRF o una descripción de la VLAN.")
        ref = self.col("vlans").document(vlan_doc_id(isla, vlan))
        ref.set({**updates, "isla": isla, "vlan": vlan, "updated_by": operator,
                 "updated_operation_id": operation_id, "updated_at": utcnow()}, merge=True)
        return ref.get().to_dict()

    # ------------------------------------------------------------------
    # Loopbacks automáticas
    # ------------------------------------------------------------------
    @staticmethod
    def _loopback_pool(start: str, end: str) -> list[str]:
        first, last = int(IPv4Address(start)), int(IPv4Address(end))
        if last < first or last - first > 4096:
            raise InventoryError("Rango de loopbacks mal configurado.")
        return [str(IPv4Address(i)) for i in range(first, last + 1)]

    def loopback_for_service(self, service_id: str) -> str | None:
        if not service_id:
            return None
        for snap in self._where("loopbacks", "service_id", "==", service_id).stream():
            return snap.to_dict()["ip"]
        return None

    def peek_loopback(self, service_id: str, start: str, end: str) -> str:
        """Loopback que tendría el servicio (la suya o la siguiente libre), sin reservarla."""
        existing = self.loopback_for_service(service_id)
        if existing:
            return existing
        used = {snap.id for snap in self.col("loopbacks").stream()}
        for ip in self._loopback_pool(start, end):
            if ip not in used:
                return ip
        raise ConflictError("No quedan loopbacks libres en el rango configurado.")

    def assign_loopback(self, service_id: str, operator: str, operation_id: str, start: str, end: str) -> str:
        """Asigna (o reutiliza) la loopback /32 del servicio de forma atómica."""
        pool = self._loopback_pool(start, end)

        def run(transaction):
            for snap in self._where("loopbacks", "service_id", "==", service_id).stream(transaction=transaction):
                return snap.to_dict()["ip"]
            used = {snap.id for snap in self.col("loopbacks").stream(transaction=transaction)}
            for ip in pool:
                if ip in used:
                    continue
                ref = self.col("loopbacks").document(ip)
                if ref.get(transaction=transaction).exists:
                    continue
                transaction.set(ref, {"ip": ip, "service_id": service_id, "assigned_by": operator,
                                      "assigned_operation_id": operation_id, "assigned_at": utcnow()})
                return ip
            raise ConflictError("No quedan loopbacks libres en el rango configurado.")

        return self._run_transaction(run)
