"""Chasis de una isla según la región y los IDs configurados en ISLAS."""

import pytest


def test_resuelve_documento_chasis_de_isla_y_region(client, repo):
    repo.col("ISLAS").document("depto").set({
        "NOMBRE": "CALZON VIEJO", "region": "DEPARTAMENTAL", "chasis_diponibles": "1",
    })
    repo.col("ISLAS").document("metro").set({
        "NOMBRE": "CALZON VIEJO", "region": "METROPOLITANA", "chasis_diponibles": "2",
    })
    equipo = {"nombre": "Chasis 1", "id_fisico": "123", "puerto": "[1,2]", "slot": "[1,3,5,7,9]"}
    repo.col("EQUIPO_CHASIS").document("1").set(equipo)
    repo.col("EQUIPO_CHASIS").document("2").set({"nombre": "Otro chasis"})

    response = client.get("/api/chasis", params={"region": "DEPARTAMENTAL", "isla": "CALZON VIEJO"})

    assert response.status_code == 200
    assert response.json() == {"chasis": [{**equipo, "id": "1"}]}


@pytest.mark.parametrize("disponibles", [[], None, "", ["1", "2", "1"]])
def test_disponibilidad_vacia_y_lista_de_ids(client, repo, disponibles):
    repo.col("ISLAS").document("isla").set({
        "NOMBRE": "CARMEN", "region": "METROPOLITANA", "chasis_diponibles": disponibles,
    })
    for doc_id in ("1", "2"):
        repo.col("EQUIPO_CHASIS").document(doc_id).set({"nombre": f"Chasis {doc_id}"})

    response = client.get("/api/chasis?region=METROPOLITANA&isla=CARMEN")

    assert response.status_code == 200
    assert [ch["id"] for ch in response.json()["chasis"]] == (["1", "2"] if disponibles else [])


def test_chasis_inexistente_conserva_operation_id(client, repo):
    repo.col("ISLAS").document("isla").set({
        "NOMBRE": "CARMEN", "region": "METROPOLITANA", "chasis_diponibles": "1",
    })
    response = client.get("/api/chasis?region=METROPOLITANA&isla=CARMEN")
    assert response.status_code == 404
    assert "EQUIPO_CHASIS" in response.json()["detail"]
    assert response.json()["operation_id"] == response.headers["X-Operation-ID"]


def test_isla_de_otra_region_no_devuelve_chasis(client, repo):
    repo.col("ISLAS").document("isla").set({"NOMBRE": "CARMEN", "region": "METROPOLITANA"})
    response = client.get("/api/chasis?region=DEPARTAMENTAL&isla=CARMEN")
    assert response.status_code == 404


@pytest.mark.parametrize("query", ["region=OTRA&isla=CARMEN", "region=METROPOLITANA", "region=METROPOLITANA&isla="])
def test_parametros_invalidos(client, query):
    assert client.get(f"/api/chasis?{query}").status_code == 422
