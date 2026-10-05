"""Requerimientos de octubre 2026: islas, VLANs con RD/VRF y loopbacks automáticas."""

from conftest import OPERATOR, SAMPLE_XLSX

SHEET = "10.20.38.0"


def _alta(client, service_id, **extra):
    data = {"id_servicio": service_id, "cliente": "CLIENTE", "sin_factibilidad": True, **extra}
    return client.post("/api/altas", json={"data": data}, headers=OPERATOR)


def test_sheet_isla_filters_segments(client):
    assert client.get("/api/islas").json()["has_unassigned"] is True
    unassigned = client.get("/api/segments", params={"isla": ""}).json()["segments"]
    assert unassigned and all(not s["isla"] for s in unassigned)

    res = client.put(f"/api/sheets/{SHEET}/isla", json={"isla": "  el carmen "}, headers=OPERATOR)
    assert res.status_code == 200, res.text
    assert res.json()["isla"] == "EL CARMEN"

    islas = client.get("/api/islas").json()["islas"]
    assert "EL CARMEN" in islas
    segments = client.get("/api/segments", params={"isla": "El Carmen"}).json()["segments"]
    assert segments and {s["sheet"] for s in segments} == {SHEET}
    assert all("available_ips" not in s for s in segments)
    assert client.get("/api/segments", params={"isla": "OTRA"}).json()["segments"] == []


def test_set_isla_requires_operator_and_existing_sheet(client):
    assert client.put(f"/api/sheets/{SHEET}/isla", json={"isla": "X"}).status_code == 400
    assert client.put("/api/sheets/10.99.99.0/isla", json={"isla": "X"}, headers=OPERATOR).status_code == 404


def test_import_keeps_and_sets_isla(client):
    def upload(isla=None):
        data = {"mode": "merge"}
        if isla is not None:
            data["isla"] = isla
        with SAMPLE_XLSX.open("rb") as fh:
            files = {"file": ("inv.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            return client.post("/api/inventory/import", files=files, data=data, headers=OPERATOR)

    assert upload("monte verde").status_code == 200
    assert {s["isla"] for s in client.get("/api/segments").json()["segments"]} == {"MONTE VERDE"}
    # Reimportar sin isla conserva la que ya tenía el segmento.
    assert upload().status_code == 200
    sheets = {s["sheet"]: s for s in client.get("/api/sheets").json()["details"]}
    assert sheets[SHEET]["isla"] == "MONTE VERDE"


def test_vlan_catalog_upsert_and_listing(client):
    res = client.put("/api/vlans", json={"isla": "Carmen", "vlan": "3740", "rd": "6458:11270",
                                         "vrf_name": "INTERNET_GT_METRO"}, headers=OPERATOR)
    assert res.status_code == 200, res.text
    # Un campo vacío no borra lo guardado.
    client.put("/api/vlans", json={"isla": "CARMEN", "vlan": "3740", "vlan_desc": "CLIENTES"}, headers=OPERATOR)
    vlans = client.get("/api/vlans", params={"isla": "carmen"}).json()["vlans"]
    assert len(vlans) == 1
    assert vlans[0] | {} == {**vlans[0], "rd": "6458:11270", "vrf_name": "INTERNET_GT_METRO",
                             "vlan_desc": "CLIENTES", "isla": "CARMEN", "vlan": "3740"}
    assert client.put("/api/vlans", json={"vlan": "9999", "rd": "1"}, headers=OPERATOR).status_code == 400
    assert client.put("/api/vlans", json={"vlan": "10"}, headers=OPERATOR).status_code == 400


def test_alta_saves_vlan_data_for_next_time(client):
    res = _alta(client, "S-V", isla="CARMEN", vlan_num="3740", rd="6458:1", vrf_name="VRF_A", vrf_desc="D VRF",
                desc_vlan="D VLAN")
    assert res.status_code == 200, res.text
    vlan = client.get("/api/vlans", params={"isla": "CARMEN"}).json()["vlans"][0]
    assert (vlan["rd"], vlan["vrf_name"], vlan["vrf_desc"], vlan["vlan_desc"]) == ("6458:1", "VRF_A", "D VRF", "D VLAN")


def test_loopbacks_are_sequential_idempotent_and_preview_does_not_reserve(client):
    preview = client.get("/api/loopbacks/next", params={"service_id": "S-1"}).json()
    assert preview == {"ip": "10.212.100.1", "cidr": "10.212.100.1/32", "assigned": False}
    text = client.post("/api/generate-format", json={"data": {"id_servicio": "S-1", "loopback_auto": True}}).json()
    assert "LOOPBACK 10.212.100.1/32" in text["formatted_text"]
    assert client.get("/api/loopbacks/next").json()["ip"] == "10.212.100.1"  # la vista previa no reserva

    first = _alta(client, "S-1", loopback_auto=True).json()
    assert "LOOPBACK 10.212.100.1/32" in first["formatted_text"]
    assert "LOOPBACK 5 :  10.212.100.1" in first["formatted_text"]
    again = _alta(client, "S-1", loopback_auto=True, observaciones="CAMBIO").json()
    assert "LOOPBACK 10.212.100.1/32" in again["formatted_text"]  # el mismo servicio conserva su loopback
    second = _alta(client, "S-2", loopback_auto=True).json()
    assert "LOOPBACK 10.212.100.2/32" in second["formatted_text"]
    assert client.get("/api/loopbacks/next", params={"service_id": "S-1"}).json()["assigned"] is True
    assert client.get(f"/api/altas/{second['alta_id']}").json()["loopback"] == "10.212.100.2"


def test_manual_loopback_is_ignored_without_checkbox(client):
    res = _alta(client, "S-3", loopback="192.0.2.1/32").json()
    assert "LOOPBACK" not in res["formatted_text"]


def test_loopback_pool_exhausted(client):
    defaults = client.app.state.claro.catalog.network_defaults
    original = (defaults.loopback_pool_start, defaults.loopback_pool_end)
    defaults.loopback_pool_start = defaults.loopback_pool_end = "10.212.100.250"
    try:
        assert _alta(client, "S-A", loopback_auto=True).status_code == 200
        res = _alta(client, "S-B", loopback_auto=True)
        assert res.status_code == 409
        assert "loopbacks libres" in res.json()["detail"]
    finally:
        defaults.loopback_pool_start, defaults.loopback_pool_end = original


def test_monitoring_psk_comes_from_environment(client, monkeypatch):
    client.app.state.claro.catalog.network_defaults.psk_monitoreo = "PSK-ENTORNO"
    try:
        res = _alta(client, "S-P", loopback_auto=True, psk="NO-SE-USA").json()
        assert res["formatted_text"].endswith("PRE-SHARED KEY: PSK-ENTORNO")
    finally:
        client.app.state.claro.catalog.network_defaults.psk_monitoreo = ""
