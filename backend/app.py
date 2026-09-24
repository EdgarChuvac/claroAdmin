import os
import shutil
from typing import Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .excel_parser import ExcelIPAMReader
from .format_generator import generate_format_text

app = FastAPI(title="Claro CENAM - Service Manager & Alta Generator")

# CORS enabled
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULT_EXCEL_PATH = os.path.join(DATA_DIR, "ejemplo_inventario_ips.xlsx")
ACTIVE_EXCEL_PATH = DEFAULT_EXCEL_PATH

# Request models
class AssignIPRequest(BaseModel):
    sheet_name: str
    row: int
    col_val: int
    client_id: str

class GenerateFormatRequest(BaseModel):
    data: Dict[str, Any]

@app.get("/api/status")
def get_status():
    global ACTIVE_EXCEL_PATH
    return {
        "status": "ok",
        "excel_path": ACTIVE_EXCEL_PATH,
        "excel_exists": os.path.exists(ACTIVE_EXCEL_PATH)
    }

@app.get("/api/sheets")
def get_sheets():
    global ACTIVE_EXCEL_PATH
    if not os.path.exists(ACTIVE_EXCEL_PATH):
        raise HTTPException(status_code=404, detail="Archivo Excel no encontrado.")
    reader = ExcelIPAMReader(ACTIVE_EXCEL_PATH)
    sheets = reader.get_sheet_names()
    return {"sheets": sheets, "current_file": os.path.basename(ACTIVE_EXCEL_PATH)}

@app.get("/api/blocks")
def get_blocks(sheet: str):
    global ACTIVE_EXCEL_PATH
    if not os.path.exists(ACTIVE_EXCEL_PATH):
        raise HTTPException(status_code=404, detail="Archivo Excel no encontrado.")
    reader = ExcelIPAMReader(ACTIVE_EXCEL_PATH)
    blocks = reader.parse_sheet(sheet)
    return {"sheet": sheet, "blocks": [b.to_dict() for b in blocks]}

@app.post("/api/upload-excel")
async def upload_excel(file: UploadFile = File(...)):
    global ACTIVE_EXCEL_PATH
    os.makedirs(DATA_DIR, exist_ok=True)
    save_path = os.path.join(DATA_DIR, file.filename)
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    ACTIVE_EXCEL_PATH = save_path
    
    reader = ExcelIPAMReader(ACTIVE_EXCEL_PATH)
    sheets = reader.get_sheet_names()
    return {
        "message": f"Archivo '{file.filename}' cargado exitosamente.",
        "filename": file.filename,
        "sheets": sheets
    }

@app.post("/api/use-sample-excel")
def use_sample_excel():
    global ACTIVE_EXCEL_PATH
    ACTIVE_EXCEL_PATH = DEFAULT_EXCEL_PATH
    reader = ExcelIPAMReader(ACTIVE_EXCEL_PATH)
    sheets = reader.get_sheet_names()
    return {
        "message": "Usando archivo Excel de ejemplo",
        "filename": os.path.basename(DEFAULT_EXCEL_PATH),
        "sheets": sheets
    }

@app.post("/api/assign-ip")
def assign_ip(req: AssignIPRequest):
    global ACTIVE_EXCEL_PATH
    if not os.path.exists(ACTIVE_EXCEL_PATH):
        raise HTTPException(status_code=404, detail="Archivo Excel no encontrado.")
    reader = ExcelIPAMReader(ACTIVE_EXCEL_PATH)
    success = reader.assign_ip(req.sheet_name, req.row, req.col_val, req.client_id)
    if not success:
        raise HTTPException(status_code=400, detail="No se pudo asignar la IP en el Excel.")
    return {"message": f"IP asignada exitosamente al cliente {req.client_id}."}

@app.post("/api/generate-format")
def generate_format(req: GenerateFormatRequest):
    formatted_text = generate_format_text(req.data)
    return {"formatted_text": formatted_text}

# Mount static frontend
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=True)
