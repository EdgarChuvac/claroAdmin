"""Inventario de IPs: segmentos /24, subredes, importación y exportación de Excel."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from zipfile import BadZipFile

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from openpyxl.utils.exceptions import InvalidFileException

from ...core import tracing
from ...core.errors import InventoryError
from ...services.excel_export import build_inventory_workbook
from ...services.excel_import import parse_inventory_excel
from ..dependencies import (
    OperatorDep,
    StateDep,
    serialize,
    validated_sheet,
)

logger = logging.getLogger("claro.api")
router = APIRouter()


@router.get("/api/sheets")
def get_sheets(state: StateDep) -> dict[str, Any]:
    sheets = state.repo.list_sheets()
    return {"sheets": [s["sheet"] for s in sheets], "details": serialize(sheets)}

@router.get("/api/blocks")
def get_blocks(state: StateDep, sheet: str = Query(min_length=7, max_length=15)) -> dict[str, Any]:
    sheet = validated_sheet(sheet)
    return {"sheet": sheet, "blocks": serialize(state.repo.get_blocks(sheet))}

@router.post("/api/inventory/import")
async def import_inventory(
    state: StateDep,
    operator: OperatorDep,
    file: Annotated[UploadFile, File(description="Inventario Excel en formato .xlsx")],
    mode: Annotated[Literal["merge", "replace"], Form()] = "merge",
    confirm_replace: Annotated[bool, Form()] = False,
    isla: Annotated[str, Form(max_length=60)] = "",
) -> dict[str, Any]:
    original_name = tracing.clean_text(Path(file.filename or "").name, 120)
    tracing.audit("inventory.import", filename=original_name, mode=mode)
    if Path(original_name).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .xlsx.")
    if mode == "replace" and not confirm_replace:
        raise HTTPException(status_code=400, detail="Confirme el reemplazo: se borrarán las IPs de las hojas importadas.")

    max_bytes = state.settings.max_upload_bytes
    content = await file.read(max_bytes + 1)
    await file.close()
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"El archivo excede el límite de {state.settings.max_upload_mb} MB.")
    if not content.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="El archivo no es un Excel .xlsx válido.")

    try:
        blocks, ignored = await run_in_threadpool(parse_inventory_excel, content)
    except InventoryError:
        raise
    except (BadZipFile, InvalidFileException, OSError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo Excel.") from exc

    ctx = tracing.current()
    result = await run_in_threadpool(
        lambda: state.repo.import_inventory(
            blocks, mode=mode, filename=original_name, operator=operator,
            operation_id=ctx.operation_id if ctx else "", ignored_sheets=ignored,
            isla=tracing.clean_text(isla, 60),
        )
    )
    summary = result.to_dict()
    tracing.audit("inventory.import", filename=original_name, mode=mode, import_id=result.import_id,
                  sheets=result.sheets, ips_written=result.ips_written, conflicts=len(result.conflicts))
    logger.info("Inventario importado", extra={"import_id": result.import_id, "sheets": result.sheets})
    return {"message": "Inventario cargado en Firebase.", **summary,
            "operation_id": tracing.current_operation_id()}

@router.get("/api/inventory/export")
def export_inventory(state: StateDep) -> Response:
    content = build_inventory_workbook(state.repo.inventory_snapshot())
    tracing.audit("inventory.export", size_bytes=len(content))
    filename = f"inventario_ips_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
