"""Lectura del Excel de inventario subido por el usuario (con protección contra zip bombs)."""

from __future__ import annotations

import io
import zipfile

from ..core.errors import InventoryError
from .excel_parser import ExcelIPAMReader, normalize_sheet_name

MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


def _check_zip_bomb(content: bytes) -> None:
    """Rechaza archivos cuyo contenido descomprimido es desproporcionado."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        total = sum(info.file_size for info in archive.infolist())
    if total > MAX_UNCOMPRESSED_BYTES:
        raise InventoryError("El Excel es demasiado grande una vez descomprimido.")

def parse_inventory_excel(content: bytes) -> tuple[dict[str, list], list[str]]:
    _check_zip_bomb(content)
    reader = ExcelIPAMReader(content)
    blocks_by_sheet: dict[str, list] = {}
    ignored: list[str] = []
    for sheet in reader.get_sheet_names():
        normalized = normalize_sheet_name(sheet)
        if normalized is None:
            ignored.append(sheet)
            continue
        if normalized in blocks_by_sheet:
            raise InventoryError(f"Hay dos hojas para el mismo segmento {normalized}. Unifíquelas en una sola.")
        blocks_by_sheet[normalized] = reader.parse_sheet(sheet)
    return blocks_by_sheet, ignored
