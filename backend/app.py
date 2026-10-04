"""API de Claro CENAM Service Manager.

La persistencia vive en Cloud Firestore (``backend.repository``). El Excel solo
se usa como formato de importación/exportación del inventario de IPs.
"""

from __future__ import annotations

import io
import logging
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote
from zipfile import BadZipFile

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import tracing
from .catalog import Catalog, Central, load_catalog
from .excel_export import build_inventory_workbook
from .excel_parser import ExcelIPAMReader, normalize_sheet_name
from .firebase_client import create_firestore_handle, create_memory_handle
from .format_generator import generate_format_text
from .repository import InventoryError, InventoryRepository
from .settings import BASE_DIR, Settings, get_settings

APP_VERSION = "2.0.0"
SAMPLE_EXCEL_PATH = BASE_DIR / "data" / "ejemplo_inventario_ips.xlsx"
FRONTEND_DIR = BASE_DIR / "frontend"

logger = logging.getLogger("claro.api")


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


def _validate_service_id(value: str) -> str:
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
        return _validate_service_id(value)


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ips: list[str] = Field(min_length=1, max_length=64)
    service_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("service_id")
    @classmethod
    def _check_service(cls, value: str) -> str:
        return _validate_service_id(value)

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

    titulo: str = "INTERNET CORPORATIVO"
    id_servicio: str = ""
    cliente: str = ""
    disenador: str = ""
    tel_disenador: str = ""
    fecha: str = ""
    factibilidad_bloque: str = ""
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
        _validate_service_id(value.id_servicio)
        if not value.cliente.strip():
            raise ValueError("El nombre del cliente es obligatorio para registrar el alta.")
        return value


# ---------------------------------------------------------------------------
# Estado de la aplicación
# ---------------------------------------------------------------------------


class AppState:
    settings: Settings
    repo: InventoryRepository
    catalog: Catalog
    backend: str


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


def _validated_sheet(value: str) -> str:
    normalized = normalize_sheet_name(value)
    if normalized is None:
        raise HTTPException(status_code=400, detail="Segmento inválido: use la red base /24, p. ej. 10.20.38.0.")
    return normalized


def _service_id_param(value: str) -> str:
    try:
        return _validate_service_id(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_state(settings: Settings) -> AppState:
    state = AppState()
    state.settings = settings
    state.catalog = load_catalog(settings.config_dir)
    handle = create_memory_handle() if settings.data_backend == "memory" else create_firestore_handle(settings)
    state.backend = handle.backend
    state.repo = InventoryRepository(handle, settings.firestore_collection_prefix,
                                     settings.operations_retention_days)
    if settings.data_backend == "memory" and settings.memory_seed_sample and SAMPLE_EXCEL_PATH.is_file():
        blocks, ignored = parse_inventory_excel(SAMPLE_EXCEL_PATH.read_bytes())
        state.repo.import_inventory(blocks, mode="replace", filename=SAMPLE_EXCEL_PATH.name,
                                    operator="sistema", operation_id="SEED", ignored_sheets=ignored)
        logger.info("Inventario de demostración cargado en memoria")
    return state


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tracing.configure_logging(settings)
    if not hasattr(app.state, "claro"):
        app.state.claro = build_state(settings)
    logger.info("Aplicación iniciada", extra={"version": APP_VERSION, "backend": app.state.claro.backend,
                                               "env": settings.app_env})
    yield


app = FastAPI(title="Claro CENAM - Service Manager", version=APP_VERSION, lifespan=lifespan)


def get_state(request: Request) -> AppState:
    return request.app.state.claro


def require_operator(request: Request) -> str:
    ctx = tracing.current()
    operator = ctx.operator if ctx else ""
    if not operator:
        raise HTTPException(status_code=400, detail="Indique su nombre de operador antes de realizar cambios.")
    return operator


StateDep = Annotated[AppState, Depends(get_state)]
OperatorDep = Annotated[str, Depends(require_operator)]


# ---------------------------------------------------------------------------
# Middleware de trazabilidad
# ---------------------------------------------------------------------------


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


@app.middleware("http")
async def operation_tracing(request: Request, call_next):
    ctx = tracing.OperationContext(
        operation_id=tracing.new_operation_id(),
        method=request.method,
        path=request.url.path,
        operator=tracing.clean_text(unquote(request.headers.get("x-operator", "")), tracing.OPERATOR_MAX_LEN),
        client_session=tracing.clean_text(request.headers.get("x-client-session", ""), 64),
        client_ip=request.client.host if request.client else "",
    )
    token = tracing.set_context(ctx)
    status_code = 500
    error: str | None = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        error = getattr(request.state, "error_detail", None)
        response.headers["X-Operation-ID"] = ctx.operation_id
        return response
    except Exception:
        # Los errores no controlados se atienden aquí (y no en ServerErrorMiddleware)
        # para que la respuesta conserve el ID de operación.
        logger.exception("Error no controlado")
        status_code = 500
        error = "internal_error"
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno. Comparta el ID de operación con soporte técnico.",
                     "code": "internal_error", "operation_id": ctx.operation_id},
            headers={"X-Operation-ID": ctx.operation_id},
        )
    finally:
        is_api = ctx.path.startswith("/api/")
        level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
        if is_api or status_code >= 400:
            logger.log(level, "%s %s -> %s", ctx.method, ctx.path, status_code, extra={
                "status_code": status_code, "duration_ms": ctx.elapsed_ms(),
                "action": ctx.action or None, "client_ip": ctx.client_ip,
                "client_session": ctx.client_session or None,
            })
        state: AppState | None = getattr(request.app.state, "claro", None)
        should_persist = is_api and (
            ctx.persist or (status_code >= 400 and status_code not in (404, 405)) or
            (state is not None and state.settings.persist_read_operations)
        )
        if state is not None and should_persist and ctx.path != "/api/health":
            record = {
                "operation_id": ctx.operation_id,
                "action": ctx.action or f"{ctx.method} {ctx.path}",
                "method": ctx.method,
                "path": ctx.path,
                "status_code": status_code,
                "outcome": "ok" if status_code < 400 else "error",
                "operator": ctx.operator or None,
                "client_session": ctx.client_session or None,
                "client_ip": ctx.client_ip or None,
                "duration_ms": ctx.elapsed_ms(),
                "service_id": ctx.details.get("service_id"),
                "details": _serialize(ctx.details),
                "error": error,
                "created_at": ctx.started_at,
            }
            try:
                await run_in_threadpool(state.repo.save_operation, record)
            except Exception:  # la auditoría nunca debe romper la respuesta
                logger.exception("No se pudo guardar la operación en Firestore")
        tracing.reset_context(token)


def _error_response(request: Request, status_code: int, detail: Any, code: str) -> JSONResponse:
    request.state.error_detail = detail if isinstance(detail, str) else code
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "code": code, "operation_id": tracing.current_operation_id()},
    )


@app.exception_handler(InventoryError)
async def inventory_error_handler(request: Request, exc: InventoryError):
    return _error_response(request, exc.status_code, exc.message, exc.code)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    return _error_response(request, exc.status_code, exc.detail, "http_error")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    messages = []
    for err in exc.errors():
        location = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "data"))
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        messages.append(f"{location}: {msg}" if location else msg)
    return _error_response(request, 422, "; ".join(messages) or "Solicitud inválida.", "validation_error")


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Error no controlado")
    return _error_response(
        request, 500,
        "Error interno. Comparta el ID de operación con soporte técnico.", "internal_error",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health(state: StateDep) -> dict[str, Any]:
    state.repo.ping()
    return {"status": "ok", "backend": state.backend, "version": APP_VERSION}


@app.get("/api/status")
def get_status(state: StateDep) -> dict[str, Any]:
    sheets = state.repo.list_sheets()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "backend": state.backend,
        "environment": state.settings.app_env,
        "inventory": {
            "sheets": len(sheets),
            "available": sum(s.get("available_count", 0) for s in sheets),
            "assigned": sum(s.get("assigned_count", 0) for s in sheets),
        },
        "operation_id": tracing.current_operation_id(),
    }


@app.get("/api/config")
def get_config(state: StateDep) -> dict[str, Any]:
    centrales = state.repo.list_centrales()
    source = "firestore"
    if not centrales:
        centrales = [c.model_dump() for c in state.catalog.centrales]
        source = "archivo"
    return {
        **state.catalog.to_public_dict(),
        "centrales": _serialize(centrales),
        "centrales_source": source,
        "max_upload_mb": state.settings.max_upload_mb,
        "backend": state.backend,
        "version": APP_VERSION,
    }


@app.get("/api/sheets")
def get_sheets(state: StateDep) -> dict[str, Any]:
    sheets = state.repo.list_sheets()
    return {"sheets": [s["sheet"] for s in sheets], "details": _serialize(sheets)}


@app.get("/api/blocks")
def get_blocks(state: StateDep, sheet: str = Query(min_length=7, max_length=15)) -> dict[str, Any]:
    sheet = _validated_sheet(sheet)
    return {"sheet": sheet, "blocks": _serialize(state.repo.get_blocks(sheet))}


@app.post("/api/inventory/import")
async def import_inventory(
    state: StateDep,
    operator: OperatorDep,
    file: Annotated[UploadFile, File(description="Inventario Excel en formato .xlsx")],
    mode: Annotated[Literal["merge", "replace"], Form()] = "merge",
    confirm_replace: Annotated[bool, Form()] = False,
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
        )
    )
    summary = result.to_dict()
    tracing.audit("inventory.import", filename=original_name, mode=mode, import_id=result.import_id,
                  sheets=result.sheets, ips_written=result.ips_written, conflicts=len(result.conflicts))
    logger.info("Inventario importado", extra={"import_id": result.import_id, "sheets": result.sheets})
    return {"message": "Inventario cargado en Firebase.", **summary,
            "operation_id": tracing.current_operation_id()}


@app.get("/api/inventory/export")
def export_inventory(state: StateDep) -> Response:
    content = build_inventory_workbook(state.repo.inventory_snapshot())
    tracing.audit("inventory.export", size_bytes=len(content))
    filename = f"inventario_ips_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/reservations")
def reserve_ips(req: ReservationRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    tracing.audit("ip.reserve", service_id=req.service_id, ips=req.ips, purpose=req.purpose)
    reserved = state.repo.reserve(req.ips, req.service_id, operator,
                                  tracing.current_operation_id(), req.purpose)
    logger.info("IPs reservadas", extra={"ips": req.ips, "service_id": req.service_id})
    return {
        "message": f"{len(reserved)} IP(s) reservada(s) para el servicio {req.service_id}.",
        "reserved": _serialize(reserved),
        "operation_id": tracing.current_operation_id(),
    }


@app.post("/api/reservations/release")
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


@app.get("/api/services/{service_id}")
def get_service(service_id: str, state: StateDep) -> dict[str, Any]:
    service_id = _service_id_param(service_id)
    return {
        "service_id": service_id,
        "ips": _serialize(state.repo.search_service(service_id)),
        "altas": _serialize([_alta_summary(a) for a in state.repo.list_altas(service_id, 20)]),
    }


@app.post("/api/generate-format")
def generate_format(req: GenerateFormatRequest, state: StateDep) -> dict[str, str]:
    """Vista previa: genera el texto sin registrarlo."""
    data = req.data.model_dump(exclude_none=True, exclude_unset=True)
    return {"formatted_text": generate_format_text(data, state.catalog)}


def _alta_summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: doc.get(k) for k in (
        "alta_id", "service_id", "cliente", "tipo_servicio", "ip_wan", "operator",
        "operation_id", "created_at",
    )}


@app.post("/api/altas")
def create_alta(req: AltaRequest, state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    """Genera el formato de alta y lo registra en la colección ``altas``."""
    data = req.data.model_dump(exclude_none=True, exclude_unset=True)
    text = generate_format_text(data, state.catalog)
    service_id = _validate_service_id(req.data.id_servicio)
    tracing.audit("alta.create", service_id=service_id, cliente=req.data.cliente)
    record = {
        "service_id": service_id,
        "cliente": req.data.cliente.strip(),
        "tipo_servicio": req.data.titulo,
        "ip_wan": req.data.ip_wan,
        "red_wan": req.data.red_wan,
        "isla": req.data.isla,
        "vlan": req.data.vlan_num,
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
        "created_at": _serialize(doc["created_at"]),
        "formatted_text": text,
        "operation_id": tracing.current_operation_id(),
    }


@app.get("/api/altas")
def list_altas(
    state: StateDep,
    service_id: str = Query(default="", max_length=100),
    limit: int = Query(default=30, ge=1, le=200),
) -> dict[str, Any]:
    service_id = tracing.clean_text(service_id, 100)
    return {"altas": _serialize([_alta_summary(a) for a in state.repo.list_altas(service_id, limit)])}


@app.get("/api/altas/{alta_id}")
def get_alta(alta_id: str, state: StateDep) -> dict[str, Any]:
    doc = state.repo.get_alta(tracing.clean_text(alta_id, 40))
    return _serialize({k: v for k, v in doc.items() if k != "content_hash"})


@app.get("/api/operations/{operation_id}")
def get_operation(operation_id: str, state: StateDep) -> dict[str, Any]:
    operation_id = operation_id.strip().upper()
    if not tracing.OPERATION_ID_RE.match(operation_id):
        raise HTTPException(status_code=400, detail="Formato de ID de operación inválido (OP-AAAAMMDD-XXXXXXXXXXXX).")
    return _serialize(state.repo.get_operation(operation_id))


@app.get("/api/operations")
def list_operations(
    state: StateDep,
    operator: str = Query(default="", max_length=80),
    service_id: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    ops = state.repo.list_operations(tracing.clean_text(operator, 80), tracing.clean_text(service_id, 100), limit)
    return {"operations": _serialize(ops)}


@app.post("/api/centrales/sync")
def sync_centrales(state: StateDep, operator: OperatorDep) -> dict[str, Any]:
    """Carga el catálogo de ``config/centrales.json`` en Firestore."""
    centrales = [Central(**c.model_dump()).model_dump() for c in load_catalog(state.settings.config_dir).centrales]
    count = state.repo.replace_centrales(centrales)
    tracing.audit("centrales.sync", count=count)
    return {"message": f"{count} central(es) sincronizada(s).", "operation_id": tracing.current_operation_id()}


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("backend.app:app", host=settings.app_host, port=settings.app_port)
