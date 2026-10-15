"""Consulta de regiones desde el selector de especificaciones técnicas."""

import pytest


@pytest.mark.parametrize(
    ("region", "esperadas"),
    [("METROPOLITANA", ["CARMEN", "MONTE VERDE"]), ("DEPARTAMENTAL", ["CALZON VIEJO"])],
)
def test_islas_de_region_sin_mezclar_catalogo_general(client, repo, region, esperadas):
    repo.col("ISLAS").document("id-metro-1").set({"NOMBRE": "MONTE VERDE", "region": "METROPOLITANA"})
    repo.col("ISLAS").document("id-metro-2").set({"NOMBRE": "CARMEN", "region": "METROPOLITANA"})
    repo.col("ISLAS").document("id-depto").set({"NOMBRE": "CALZON VIEJO", "region": "DEPARTAMENTAL"})
    # Los documentos de la estructura anterior no deben alimentar el selector.
    repo.col("Equipos_Transmision/REGION/DEPARTAMENTAL").document("ANTIGUA").set({})

    response = client.get("/api/islas", params={"region": region})

    assert response.status_code == 200
    assert response.json() == {"region": region, "islas": esperadas, "has_unassigned": False}


def test_region_sin_documentos_devuelve_lista_vacia(client):
    response = client.get("/api/islas?region=METROPOLITANA")

    assert response.status_code == 200
    assert response.json()["islas"] == []
    assert response.headers["X-Operation-ID"]


def test_rechaza_region_fuera_del_selector(client):
    response = client.get("/api/islas?region=OTRA")

    assert response.status_code == 422


def test_nombres_duplicados_vacios_o_invalidos(client, repo):
    for doc_id, nombre in enumerate(["CALZON VIEJO", " CALZON VIEJO ", "", "   ", None, 123]):
        repo.col("ISLAS").document(str(doc_id)).set({"NOMBRE": nombre, "region": "DEPARTAMENTAL"})
    repo.col("ISLAS").document("sin-nombre").set({"region": "DEPARTAMENTAL"})
    repo.col("ISLAS").document("sin-region").set({"NOMBRE": "OTRA ISLA"})

    response = client.get("/api/islas?region=DEPARTAMENTAL")

    assert response.status_code == 200
    assert response.json()["islas"] == ["CALZON VIEJO"]
