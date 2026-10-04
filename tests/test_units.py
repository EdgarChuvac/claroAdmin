"""Pruebas unitarias: plantillas, parser, configuración y trazabilidad."""

import base64
import io
import json
import re

import openpyxl
import pytest

from backend.catalog import default_catalog
from backend.excel_parser import ExcelIPAMReader
from backend.format_generator import generate_format_text
from backend.settings import Settings
from backend.tracing import OPERATION_ID_RE, clean_text, new_operation_id


def test_operation_ids_are_unique_and_well_formed():
    ids = {new_operation_id() for _ in range(5000)}
    assert len(ids) == 5000
    assert all(OPERATION_ID_RE.match(i) for i in ids)


def test_clean_text_strips_control_characters():
    assert clean_text("Juan\nPérez\x00", 80) == "Juan Pérez"


def test_internet_template_includes_vpn_block():
    text = generate_format_text({"titulo": "INTERNET CORPORATIVO", "cliente": "X"})
    assert "ip vpn-instance INTERNET_GT_METRO" in text
    assert "import route-policy FILTROINTERNET" in text
    assert "export route-policy EXP_INTERNET_GT_METRO" in text
    assert "traffic-policy pt-BCP38-PUBLICAS network inbound" in text
    assert text.count("vpn-target") == 13


def test_datos_template_has_no_internet_policies():
    text = generate_format_text({"titulo": "DATOS", "cliente": "X", "vrf_name": "VRF_CLIENTE",
                                 "rd": "6458:500", "vpn_targets": ["6458:500 export-extcommunity"]})
    assert text.startswith("DATOS\nDATOS X")
    assert "ALTA DE DATOS" in text
    assert "ip vpn-instance VRF_CLIENTE" in text
    assert "  vpn-target 6458:500 export-extcommunity" in text
    assert "FILTROINTERNET" not in text
    assert "BCP38" not in text
    assert "INTERNET_GT_METRO" not in text
    assert "• DATOS LOCAL 300 MBPS  (ACEPTADO)" in text


def test_vpn_block_omitted_without_vrf():
    text = generate_format_text({"titulo": "ACCESO EMPRESARIAL", "cliente": "X"})
    assert "ip vpn-instance" not in text
    assert "ALTA DE ACCESO EMPRESARIAL" in text


def test_form_values_override_template_even_if_empty():
    text = generate_format_text({"titulo": "INTERNET CORPORATIVO", "vrf_name": ""})
    assert "ip vpn-instance" not in text


def test_medio_fields_are_used():
    text = generate_format_text({
        "equipos_claro": [{"rol": "PE", "marca": "HUAWEI", "modelo": "NE40E"}],
        "enlace_medio": "RADIO",
        "obs_medio": "TENDIDO NUEVO",
        "equipo_raisecom": "RAISECOM X",
        "ips_adicionales": ["10.0.0.3"],
    })
    assert "PE HUAWEI NE40E ==> RADIO ==> (CLIENTE) RAISECOM X --> CISCO C921" in text
    assert "OBSERVACIONES DE MEDIO: TENDIDO NUEVO" in text
    assert "10.0.0.3    ADICIONAL" in text


def test_all_templates_are_valid():
    catalog = default_catalog()
    for name in catalog.services:
        text = generate_format_text({"titulo": name, "cliente": "X"}, catalog)
        assert f"ALTA DE {catalog.service(name).banner}" in text


def _workbook(rows, title="10.5.5.0") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_gateway_not_offered_when_unlabeled():
    content = _workbook([[0, "VLAN 10"], [1, ""], [2, ""], [3, "BROADCAST"]])
    block = ExcelIPAMReader(content).parse_sheet("10.5.5.0")[0]
    assert block.gateway_ip == "10.5.5.1"
    assert [i["ip"] for i in block.available_ips] == ["10.5.5.2"]


def test_service_ids_containing_gw_are_not_gateways():
    content = _workbook([[0, "VLAN 10"], [1, "GW"], [2, "CLIENTE-GWX"], [3, "BROADCAST"]])
    block = ExcelIPAMReader(content).parse_sheet("10.5.5.0")[0]
    assert block.gateway_ip == "10.5.5.1"
    assert [i["id"] for i in block.assigned_ips] == ["CLIENTE-GWX"]


def test_non_ip_sheet_is_not_inventory():
    reader = ExcelIPAMReader(_workbook([], title="Resumen"))
    assert reader.is_inventory_sheet("10.0.0.0")
    assert not reader.is_inventory_sheet("Resumen")


def _service_account() -> dict:
    return {"type": "service_account", "project_id": "demo", "client_email": "a@b"}


def test_credentials_json_plain_and_base64(monkeypatch):
    raw = json.dumps(_service_account())
    assert Settings(firebase_credentials_json=raw).firebase_credentials_info()["project_id"] == "demo"
    encoded = base64.b64encode(raw.encode()).decode()
    assert Settings(firebase_credentials_json=encoded).firebase_credentials_info()["project_id"] == "demo"
    with pytest.raises(ValueError):
        Settings(firebase_credentials_json='{"type": "user"}').firebase_credentials_info()


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("FIRESTORE_COLLECTION_PREFIX", "qa_")
    monkeypatch.setenv("MAX_UPLOAD_MB", "5")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    s = Settings()
    assert s.firestore_collection_prefix == "qa_"
    assert s.max_upload_bytes == 5 * 1024 * 1024
    assert s.log_level == "DEBUG"
    monkeypatch.setenv("FIRESTORE_COLLECTION_PREFIX", "qa/../")
    with pytest.raises(ValueError):
        Settings()


def test_collection_prefix_is_applied():
    from backend.firebase_client import create_memory_handle
    from backend.repository import InventoryRepository

    handle = create_memory_handle()
    repo = InventoryRepository(handle, "qa_")
    repo.save_operation({"operation_id": "OP-20260101-AAAAAAAAAAAA"})
    assert "qa_operations" in handle.client._data


def test_json_log_format_contains_operation_id():
    import logging

    from backend import tracing

    record = logging.makeLogRecord({"msg": "hola %s", "args": ("mundo",), "levelname": "INFO", "name": "x"})
    ctx = tracing.OperationContext(operation_id="OP-20260101-ABCDEFABCDEF", operator="Ana")
    token = tracing.set_context(ctx)
    try:
        tracing.ContextFilter().filter(record)
    finally:
        tracing.reset_context(token)
    payload = json.loads(tracing.JsonFormatter().format(record))
    assert payload["operation_id"] == "OP-20260101-ABCDEFABCDEF"
    assert payload["operator"] == "Ana"
    assert payload["message"] == "hola mundo"
    assert re.match(r"\d{4}-\d{2}-\d{2}T", payload["ts"])
