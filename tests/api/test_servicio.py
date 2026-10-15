"""Alta con región/medio/chasis, alta atómica, baja de servicio y cliente en las IPs."""

import io

import openpyxl
import pytest
from conftest import OPERATOR

SHEET = "10.20.38.0"


def _alta(client, service_id, **extra):
    data = {"id_servicio": service_id, "cliente": "CLIENTE", "sin_factibilidad": True, **extra}
    return client.post("/api/altas", json={"data": data}, headers=OPERATOR)


def _free_ips(client, count=1):
    blocks = client.get("/api/blocks", params={"sheet": SHEET}).json()["blocks"]
    return [ip["ip"] for b in blocks for ip in b["available_ips"]][:count]


def test_alta_imprime_region_y_chasis_desde_firestore(client):
    res = _alta(client, "S-CH", region="metropolitana", isla="MONTE VERDE", medio="FIBRA",
                chasis_id="DEMO-CH-01", chasis_slot="3", chasis_puerto="2")
    assert res.status_code == 200, res.text
    text = res.json()["formatted_text"]
    assert "CHASIS: CHASIS DEMO 01 | ID FISICO DEMO-0001 | SLOT 3 | PUERTO 2" in text
    assert "REGION METROPOLITANA" in text
    alta = client.get(f"/api/altas/{res.json()['alta_id']}").json()
    assert alta["chasis_id"] == "DEMO-CH-01" and alta["region"] == "METROPOLITANA"
    assert alta["estado"] == "ACTIVA"


@pytest.mark.parametrize(("extra", "mensaje"), [
    ({"medio": "PALOMA"}, "Medio"),
    ({"region": "OTRA"}, "Región"),
    ({"isla": "MONTE VERDE", "chasis_id": "NO-EXISTE"}, "no existe"),
    ({"isla": "CARMEN", "chasis_id": "DEMO-CH-01"}, "no pertenece"),
    ({"isla": "MONTE VERDE", "chasis_id": "DEMO-CH-01", "chasis_slot": "99"}, "slot"),
    ({"isla": "MONTE VERDE", "medio": "RADIO", "chasis_id": "DEMO-CH-01"}, "no usa chasis"),
])
def test_alta_valida_medio_region_y_chasis(client, extra, mensaje):
    res = _alta(client, "S-VAL", **extra)
    assert res.status_code in (400, 404)
    assert mensaje in res.json()["detail"]
    assert client.get("/api/altas", params={"service_id": "S-VAL"}).json()["altas"] == []


def test_vista_previa_no_imprime_chasis_vacio(client):
    data = {"id_servicio": "S-P", "cliente": "C", "sin_factibilidad": True}
    text = client.post("/api/generate-format", json={"data": data}).json()["formatted_text"]
    assert "CHASIS" not in text and "REGION" not in text


def test_si_falla_el_alta_no_queda_loopback_huerfana(client, repo, monkeypatch):
    from backend.api.routes import altas

    def falla(*_args, **_kwargs):
        raise RuntimeError("fallo simulado al generar el texto")

    monkeypatch.setattr(altas, "generate_format_text", falla)
    res = _alta(client, "S-ATOM", loopback_auto=True, isla="CARMEN", vlan_num="100", rd="65000:1")
    assert res.status_code == 500 and res.json()["operation_id"]
    assert list(repo.col("loopbacks").stream()) == []
    assert list(repo.col("vlans").stream()) == []
    assert list(repo.col("altas").stream()) == []


def test_baja_de_servicio_libera_ips_loopback_y_marca_altas(client, repo):
    ips = _free_ips(client, 2)
    assert client.post("/api/reservations", json={"ips": ips, "service_id": "S-BAJA", "cliente": "ACME"},
                       headers=OPERATOR).status_code == 200
    alta = _alta(client, "S-BAJA", loopback_auto=True, ip_wan=ips[0]).json()
    before = client.get("/api/sheets").json()["details"]
    free_before = next(s for s in before if s["sheet"] == SHEET)["available_count"]

    assert client.post("/api/services/S-BAJA/baja", json={"reason": "x"}, headers=OPERATOR).status_code == 422
    assert client.post("/api/services/S-BAJA/baja", json={"reason": "cancelado"}).status_code == 400
    res = client.post("/api/services/S-BAJA/baja", json={"reason": "Cancelado por el cliente"}, headers=OPERATOR)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ips"] == sorted(ips, key=lambda ip: int(ip.split(".")[-1]))
    assert body["loopbacks"] == [alta["loopback"]] and body["altas"] == [alta["alta_id"]]

    servicio = client.get("/api/services/S-BAJA").json()
    assert servicio["ips"] == [] and servicio["loopback"] is None
    assert servicio["altas"][0]["estado"] == "BAJA"
    after = client.get("/api/sheets").json()["details"]
    assert next(s for s in after if s["sheet"] == SHEET)["available_count"] == free_before + 2
    ip_doc = repo.col("ip_addresses").document(ips[0]).get().to_dict()
    assert ip_doc["cliente"] is None and ip_doc["released_service_id"] == "S-BAJA"

    # Sin nada activo: 404. Volver a registrar la misma alta crea una nueva (la anterior está de baja).
    assert client.post("/api/services/S-BAJA/baja", json={"reason": "otra vez"}, headers=OPERATOR).status_code == 404
    nueva = _alta(client, "S-BAJA", ip_wan=ips[0]).json()
    assert nueva["duplicate"] is False and nueva["alta_id"] != alta["alta_id"]


def test_liberar_ip_borra_el_cliente(client, repo):
    ip = _free_ips(client)[0]
    client.post("/api/reservations", json={"ips": [ip], "service_id": "S-CLI", "cliente": "ACME"}, headers=OPERATOR)
    assert repo.col("ip_addresses").document(ip).get().to_dict()["cliente"] == "ACME"
    client.post("/api/reservations/release", json={"ips": [ip], "service_id": "S-CLI", "reason": "prueba"},
                headers=OPERATOR)
    assert repo.col("ip_addresses").document(ip).get().to_dict()["cliente"] is None


def test_cliente_sobrevive_exportar_e_importar(client, repo):
    ip = _free_ips(client)[0]
    client.post("/api/reservations", json={"ips": [ip], "service_id": "S-XLS", "cliente": "BANCO DEMO"},
                headers=OPERATOR)
    exported = client.get("/api/inventory/export").content
    ws = openpyxl.load_workbook(io.BytesIO(exported))[SHEET]
    assert "S-XLS BANCO DEMO" in [c.value for c in ws["B"]]

    files = {"file": ("inv.xlsx", exported,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = client.post("/api/inventory/import", files=files, data={"mode": "replace", "confirm_replace": "true"},
                      headers=OPERATOR)
    assert res.status_code == 200, res.text
    doc = repo.col("ip_addresses").document(ip).get().to_dict()
    assert (doc["service_id"], doc["cliente"]) == ("S-XLS", "BANCO DEMO")
