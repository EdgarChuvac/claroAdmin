"""Topología: regiones (config), islas y chasis (colecciones ``islas`` y ``chasis``)."""

import pytest
from conftest import OPERATOR


def test_config_publica_regiones_y_medios_con_chasis(client):
    cfg = client.get("/api/config").json()
    assert cfg["regiones"]["METROPOLITANA"]["vlan_internet"] == "3740"
    assert cfg["regiones"]["DEPARTAMENTAL"]["vlan_internet"] == "3750"
    assert cfg["medios"]["FIBRA"]["usa_chasis"] is True
    assert cfg["medios"]["RADIO"]["usa_chasis"] is False


@pytest.mark.parametrize(
    ("region", "esperadas"),
    [("METROPOLITANA", ["CARMEN", "MONTE VERDE"]), ("departamental", ["ISLA DEMO DEPARTAMENTAL"])],
)
def test_islas_por_region_desde_la_topologia_demo(client, region, esperadas):
    response = client.get("/api/islas", params={"region": region})
    assert response.status_code == 200
    body = response.json()
    assert body["region"] == region.upper()
    assert body["islas"] == esperadas
    assert body["has_unassigned"] is True  # el Excel de ejemplo no trae isla


def test_region_desconocida_conserva_operation_id(client):
    response = client.get("/api/islas?region=OTRA")
    assert response.status_code == 400
    assert response.json()["operation_id"] == response.headers["X-Operation-ID"]


def test_registrar_isla_y_desactivarla(client):
    assert client.put("/api/islas", json={"nombre": "Antigua", "region": "DEPARTAMENTAL"}).status_code == 400
    res = client.put("/api/islas", json={"nombre": " antigua ", "region": "departamental"}, headers=OPERATOR)
    assert res.status_code == 200
    assert res.json()["isla"]["id"] == "ANTIGUA"
    assert "ANTIGUA" in client.get("/api/islas?region=DEPARTAMENTAL").json()["islas"]
    assert "ANTIGUA" in client.get("/api/islas").json()["islas"]

    client.put("/api/islas", json={"nombre": "ANTIGUA", "region": "DEPARTAMENTAL", "activo": False}, headers=OPERATOR)
    assert "ANTIGUA" not in client.get("/api/islas?region=DEPARTAMENTAL").json()["islas"]


def test_isla_con_barra_no_rompe_el_id(client):
    res = client.put("/api/islas", json={"nombre": "MONTE/VERDE NORTE", "region": "METROPOLITANA"}, headers=OPERATOR)
    assert res.status_code == 200
    assert "/" not in res.json()["isla"]["id"]


def test_chasis_de_una_isla(client):
    chasis = client.get("/api/chasis", params={"isla": "monte verde"}).json()["chasis"]
    assert [c["id"] for c in chasis] == ["DEMO-CH-01", "DEMO-CH-02"]
    assert chasis[0]["slots"] == ["1", "3", "5"]
    assert chasis[0]["isla_id"] == "MONTE-VERDE"
    assert chasis[0]["region"] == "METROPOLITANA"


def test_chasis_de_isla_no_registrada(client):
    response = client.get("/api/chasis", params={"isla": "NO EXISTE"})
    assert response.status_code == 404
    assert response.json()["operation_id"] == response.headers["X-Operation-ID"]


@pytest.mark.parametrize("query", ["", "isla=", "isla=%20"])
def test_chasis_parametros_invalidos(client, query):
    assert client.get(f"/api/chasis?{query}").status_code == 422


def test_registrar_chasis(client):
    body = {"isla": "CARMEN", "nombre": "Chasis nuevo", "slots": ["1", " 2 "], "puertos": ["10"]}
    assert client.put("/api/chasis/CH-NUEVO", json=body).status_code == 400  # sin operador
    res = client.put("/api/chasis/CH-NUEVO", json=body, headers=OPERATOR)
    assert res.status_code == 200
    assert res.json()["chasis"]["slots"] == ["1", "2"]
    assert "CH-NUEVO" in [c["id"] for c in client.get("/api/chasis?isla=CARMEN").json()["chasis"]]

    assert client.put("/api/chasis/CH-X", json={**body, "isla": "NO EXISTE"}, headers=OPERATOR).status_code == 404
    assert client.put("/api/chasis/mal%20id", json=body, headers=OPERATOR).status_code == 400


def test_migracion_desde_colecciones_antiguas(client, repo):
    from backend.services.topology import apply_topology, read_legacy_topology

    repo.col("ISLAS").document("a").set({"NOMBRE": "SAN LUCAS", "region": "DEPARTAMENTAL",
                                         "chasis_diponibles": ["7", "8"]})
    repo.col("ISLAS").document("b").set({"NOMBRE": "", "region": "DEPARTAMENTAL"})
    repo.col("EQUIPO_CHASIS").document("7").set({"nombre": "Chasis 7", "id_fisico": "123",
                                                 "puerto": "[1,2]", "slot": "[1,3,5,7,9]"})
    seed, warnings = read_legacy_topology(repo)
    assert any("sin NOMBRE" in w for w in warnings)
    assert any("EQUIPO_CHASIS/8" in w for w in warnings)
    state = client.app.state.claro
    assert apply_topology(repo, state.catalog, seed, "migración", "OP-TEST") == {"islas": 1, "chasis": 1}

    chasis = client.get("/api/chasis?isla=SAN LUCAS").json()["chasis"]
    assert chasis == [{**chasis[0], "id": "7", "slots": ["1", "3", "5", "7", "9"], "puertos": ["1", "2"],
                       "id_fisico": "123", "region": "DEPARTAMENTAL"}]
