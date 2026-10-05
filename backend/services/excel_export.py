"""Exporta el inventario de Firestore a Excel con el mismo formato que se importa.

Sirve como respaldo y para compartir el inventario fuera de la aplicación.
El archivo generado puede volver a importarse sin pérdida.
"""

from __future__ import annotations

import io
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from ..repositories.inventory import STATUS_GATEWAY, STATUS_USED

GREEN = PatternFill(start_color="92D050", end_color="92D050", fill_type="solid")
PEACH = PatternFill(start_color="F8CBAD", end_color="F8CBAD", fill_type="solid")
GREY = PatternFill(start_color="A6A6A6", end_color="A6A6A6", fill_type="solid")
BORDER = Border(*(Side(style="thin", color="BFBFBF") for _ in range(4)))
BOLD = Font(name="Calibri", size=10, bold=True)
NORMAL = Font(name="Calibri", size=10)


def _set_text(cell, value: Any) -> None:
    """Escribe siempre como texto (nunca como fórmula), sin alterar el valor."""
    cell.value = "" if value is None else str(value)
    cell.data_type = "s"


def build_inventory_workbook(snapshot: dict[str, dict[str, Any]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet_name, content in snapshot.items():
        ws = wb.create_sheet(title=sheet_name[:31])
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 28
        ips: dict[str, dict[str, Any]] = content["ips"]
        row = 1
        for seg in content["segments"]:
            base = seg["network_ip"].split("/")[0].rsplit(".", 1)[0]
            for octet in range(seg["network_octet"], seg["broadcast_octet"] + 1):
                ip = f"{base}.{octet}"
                num_cell = ws.cell(row=row, column=1, value=octet)
                label_cell = ws.cell(row=row, column=2)
                fill = None
                if octet == seg["network_octet"]:
                    _set_text(label_cell, seg.get("vlan_raw") or (f"VLAN {seg['vlan']}" if seg.get("vlan") else "RED"))
                    label_cell.font = BOLD
                    fill = GREEN
                elif octet == seg["broadcast_octet"]:
                    label_cell.value = "BROADCAST"
                    fill = GREY
                else:
                    doc = ips.get(ip, {})
                    status = doc.get("status")
                    if status == STATUS_USED:
                        _set_text(label_cell, doc.get("service_id"))
                        fill = PEACH
                    elif status == STATUS_GATEWAY or ip == seg.get("gateway_ip"):
                        label_cell.value = "GW"
                        fill = PEACH
                for cell in (num_cell, label_cell):
                    cell.border = BORDER
                    cell.alignment = Alignment(vertical="center")
                    if cell.font != BOLD:
                        cell.font = NORMAL
                    if fill:
                        cell.fill = fill
                row += 1
            row += 1  # fila vacía entre subredes
    if not wb.sheetnames:
        wb.create_sheet(title="SIN_DATOS")
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
