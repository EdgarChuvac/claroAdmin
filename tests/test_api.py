import importlib
import shutil
from pathlib import Path

from fastapi.testclient import TestClient


app_module = importlib.import_module("backend.app")
client = TestClient(app_module.app)


def test_status_does_not_expose_server_path() -> None:
    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "excel_path" not in payload
    assert "/" not in payload["excel_file"]


def test_lists_sheets_and_blocks() -> None:
    sheets_response = client.get("/api/sheets")
    blocks_response = client.get("/api/blocks", params={"sheet": "10.20.38.0"})

    assert sheets_response.status_code == 200
    assert "10.20.38.0" in sheets_response.json()["sheets"]
    assert blocks_response.status_code == 200
    first_block = blocks_response.json()["blocks"][0]
    assert first_block["network_ip"] == "10.20.38.0/27"
    assert first_block["first_available"]["ip"] == "10.20.38.6"


def test_unknown_sheet_returns_404() -> None:
    response = client.get("/api/blocks", params={"sheet": "NO-EXISTE"})

    assert response.status_code == 404


def test_upload_rejects_non_xlsx() -> None:
    response = client.post(
        "/api/upload-excel",
        files={"file": ("../../app.py", b"not an excel", "text/plain")},
    )

    assert response.status_code == 400


def test_upload_rejects_corrupt_xlsx() -> None:
    response = client.post(
        "/api/upload-excel",
        files={"file": ("corrupt.xlsx", b"PK-corrupt", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 400


def test_assignment_revalidates_availability(tmp_path: Path) -> None:
    source = Path(__file__).parent.parent / "data" / "ejemplo_inventario_ips.xlsx"
    inventory = tmp_path / "inventory.xlsx"
    shutil.copyfile(source, inventory)
    previous_path = app_module._active_excel_path
    app_module._active_excel_path = inventory

    try:
        request = {
            "sheet_name": "10.20.38.0",
            "ip": "10.20.38.6",
            "client_id": "SERVICIO-TEST-001",
        }
        first_response = client.post("/api/assign-ip", json=request)
        second_response = client.post("/api/assign-ip", json=request)
    finally:
        app_module._active_excel_path = previous_path

    assert first_response.status_code == 200
    assert second_response.status_code == 409


def test_assignment_rejects_formula_identifier() -> None:
    response = client.post(
        "/api/assign-ip",
        json={
            "sheet_name": "10.20.38.0",
            "ip": "10.20.38.6",
            "client_id": "=HYPERLINK('https://example.com')",
        },
    )

    assert response.status_code == 422


def test_assignment_rejects_blank_identifier() -> None:
    response = client.post(
        "/api/assign-ip",
        json={"sheet_name": "10.20.38.0", "ip": "10.20.38.6", "client_id": "   "},
    )

    assert response.status_code == 422


def test_generates_format_and_validates_contract() -> None:
    response = client.post(
        "/api/generate-format",
        json={
            "data": {
                "cliente": "CLIENTE DEMO",
                "id_servicio": "SERVICIO-DEMO-001",
                "titulo": "INTERNET CORPORATIVO",
                "velocidad": "300 MBPS",
                "red_wan": "10.20.38.0/27",
                "gw_wan": "10.20.38.1",
                "ip_wan": "10.20.38.6",
                "vlan_num": "3740",
            }
        },
    )

    assert response.status_code == 200
    text = response.json()["formatted_text"]
    assert "SERVICIO-DEMO-001" in text
    assert "10.20.38.0/27 RED" in text
    assert "EQUIPO: CISCO C921" in text
    assert "route-distinguisher 6458:11270" in text


def test_generate_format_rejects_unknown_fields() -> None:
    response = client.post(
        "/api/generate-format", json={"data": {"unknown": "value"}}
    )

    assert response.status_code == 422
