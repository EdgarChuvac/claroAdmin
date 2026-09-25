import os
import tempfile
import threading
from zipfile import BadZipFile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .excel_parser import ExcelIPAMReader
from .format_generator import generate_format_text

app = FastAPI(title="Claro CENAM - Service Manager", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_EXCEL_PATH = DATA_DIR / "ejemplo_inventario_ips.xlsx"
UPLOADED_EXCEL_PATH = DATA_DIR / "inventario_activo.xlsx"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

_active_excel_path = (
    UPLOADED_EXCEL_PATH if UPLOADED_EXCEL_PATH.is_file() else DEFAULT_EXCEL_PATH
)
_excel_lock = threading.RLock()


class AssignIPRequest(BaseModel):
    sheet_name: str = Field(min_length=1, max_length=31)
    ip: str = Field(min_length=7, max_length=45)
    client_id: str = Field(min_length=1, max_length=100)

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("El ID de servicio no puede estar vacío.")
        if clean_value.startswith(("=", "+", "-", "@")):
            raise ValueError("El ID de servicio no puede iniciar con un operador de fórmula.")
        return clean_value


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
    vrf_name: str = "INTERNET_GT_METRO"
    isla: str = ""
    red_wan: str = ""
    rd: str = ""
    vlan_num: str = ""
    gw_wan: str = ""
    desc_vlan: str = ""
    lan: str = ""
    lan_obs: str = ""
    ip_wan: str = ""
    loopback: str = ""
    loopback_id: str = "5"
    psk: str = ""
    equipos_claro: list[EquipmentData] = Field(default_factory=list)
    equipo_raisecom: str = "RAISECOM RAX711-L"
    vrf_gestor: str = "GESTOR_RAISECOM"
    vlan_gestor: str = "836"
    red_gestor: str = "10.40.3.0/24"
    gw_gestor: str = "10.40.3.1"
    ip_gestor_raisecom: str = "10.40.3.120"
    ruta_manual: str = ""
    vrf_desc: str = "INTERNET_PEs_METROPOLITANO_ISLA_APP"
    vpn_targets: list[str] | str | None = None


class GenerateFormatRequest(BaseModel):
    data: FormatData


def _get_active_excel_path() -> Path:
    return _active_excel_path


def _require_excel() -> Path:
    excel_path = _get_active_excel_path()
    if not excel_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo Excel no encontrado.")
    return excel_path


@app.get("/api/status")
def get_status() -> dict[str, object]:
    excel_path = _get_active_excel_path()
    return {
        "status": "ok",
        "excel_file": excel_path.name,
        "excel_exists": excel_path.is_file(),
    }


@app.get("/api/sheets")
def get_sheets() -> dict[str, object]:
    with _excel_lock:
        excel_path = _require_excel()
        sheets = ExcelIPAMReader(str(excel_path)).get_sheet_names()
    return {"sheets": sheets, "current_file": excel_path.name}


@app.get("/api/blocks")
def get_blocks(sheet: str) -> dict[str, object]:
    with _excel_lock:
        excel_path = _require_excel()
        reader = ExcelIPAMReader(str(excel_path))
        if sheet not in reader.get_sheet_names():
            raise HTTPException(status_code=404, detail="La hoja solicitada no existe.")
        blocks = reader.parse_sheet(sheet)
    return {"sheet": sheet, "blocks": [block.to_dict() for block in blocks]}


@app.post("/api/upload-excel")
async def upload_excel(
    file: Annotated[UploadFile, File(description="Inventario Excel en formato .xlsx")],
) -> dict[str, object]:
    global _active_excel_path

    original_name = Path(file.filename or "").name
    if Path(original_name).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .xlsx.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo excede el límite de 10 MB.")
    if not content.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="El archivo no es un Excel .xlsx válido.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=DATA_DIR, suffix=".xlsx", delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_path = Path(temp_file.name)

        reader = ExcelIPAMReader(str(temp_path))
        sheets = reader.get_sheet_names()
        if not sheets:
            raise HTTPException(status_code=400, detail="El Excel no contiene hojas.")

        destination = UPLOADED_EXCEL_PATH
        with _excel_lock:
            os.replace(temp_path, destination)
            temp_path = None
            _active_excel_path = destination
    except HTTPException:
        raise
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo Excel.") from exc
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()

    return {
        "message": "Inventario cargado exitosamente.",
        "filename": destination.name,
        "sheets": sheets,
    }


@app.post("/api/use-sample-excel")
def use_sample_excel() -> dict[str, object]:
    global _active_excel_path

    with _excel_lock:
        if not DEFAULT_EXCEL_PATH.is_file():
            raise HTTPException(status_code=404, detail="Excel de ejemplo no encontrado.")
        sheets = ExcelIPAMReader(str(DEFAULT_EXCEL_PATH)).get_sheet_names()
        _active_excel_path = DEFAULT_EXCEL_PATH
    return {
        "message": "Usando archivo Excel de ejemplo.",
        "filename": DEFAULT_EXCEL_PATH.name,
        "sheets": sheets,
    }


@app.post("/api/assign-ip")
def assign_ip(req: AssignIPRequest) -> dict[str, str]:
    with _excel_lock:
        excel_path = _require_excel()
        reader = ExcelIPAMReader(str(excel_path))
        if not reader.assign_ip(req.sheet_name, req.ip, req.client_id):
            raise HTTPException(
                status_code=409,
                detail="La IP ya no está disponible o no pertenece al inventario.",
            )
    return {"message": f"IP {req.ip} asignada al servicio {req.client_id}."}


@app.post("/api/generate-format")
def generate_format(req: GenerateFormatRequest) -> dict[str, str]:
    data = req.data.model_dump(exclude_none=True, exclude_unset=True)
    return {"formatted_text": generate_format_text(data)}


FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000)
