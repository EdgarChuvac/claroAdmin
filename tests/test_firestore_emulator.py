"""Integración contra el emulador oficial de Firestore.

Se ejecuta solo si ``FIRESTORE_EMULATOR_HOST`` está definido, por ejemplo::

    firebase emulators:start --only firestore --project demo-claro-admin
    FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 python -m pytest tests/test_firestore_emulator.py

En GitHub Actions corre automáticamente (ver ``.github/workflows/ci.yml``).
Valida que ``InventoryRepository`` funcione con el SDK real (consultas,
lotes y transacciones), no solo con el cliente en memoria.
"""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import SAMPLE_XLSX

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="Requiere el emulador de Firestore"
)


@pytest.fixture
def emulator_repo():
    from backend.app import parse_inventory_excel
    from backend.firebase_client import create_firestore_handle
    from backend.repository import InventoryRepository
    from backend.settings import Settings

    settings = Settings(
        data_backend="firestore",
        firebase_project_id="demo-claro-admin",
        firestore_emulator_host=os.environ["FIRESTORE_EMULATOR_HOST"],
    )
    prefix = f"t{secrets.token_hex(4)}_"
    repo = InventoryRepository(create_firestore_handle(settings), prefix)
    blocks, ignored = parse_inventory_excel(SAMPLE_XLSX.read_bytes())
    repo.import_inventory(blocks, mode="replace", filename="sample.xlsx", operator="ci",
                          operation_id="OP-CI", ignored_sheets=ignored)
    return repo


def test_full_flow_with_real_sdk(emulator_repo):
    repo = emulator_repo
    assert [s["sheet"] for s in repo.list_sheets()] == ["10.20.37.0", "10.20.38.0"]
    block = repo.get_blocks("10.20.38.0")[0]
    assert block["first_available"]["ip"] == "10.20.38.6"

    repo.reserve(["10.20.38.6", "10.20.38.7"], "S-1", "ci", "OP-1")
    assert [d["ip"] for d in repo.search_service("S-1")] == ["10.20.38.6", "10.20.38.7"]
    sheet = next(s for s in repo.list_sheets() if s["sheet"] == "10.20.38.0")
    assert sheet["assigned_count"] == 6

    # merge con el SDK real: escrituras protegidas + recálculo transaccional de contadores
    from backend.app import parse_inventory_excel

    blocks, ignored = parse_inventory_excel(SAMPLE_XLSX.read_bytes())
    result = repo.import_inventory(blocks, mode="merge", filename="s.xlsx", operator="ci",
                                   operation_id="OP-M", ignored_sheets=ignored)
    assert {c["ip"] for c in result.conflicts} == {"10.20.38.6", "10.20.38.7"}
    sheet = next(s for s in repo.list_sheets() if s["sheet"] == "10.20.38.0")
    assert sheet["assigned_count"] == 6

    repo.release(["10.20.38.7"], "S-1", "ci", "OP-2", "prueba")
    assert [d["ip"] for d in repo.search_service("S-1")] == ["10.20.38.6"]

    doc, dup = repo.create_alta({"service_id": "S-1", "formatted_text": "TEXTO", "operator": "ci"})
    assert not dup
    assert repo.create_alta({"service_id": "S-1", "formatted_text": "TEXTO"})[1] is True
    assert repo.list_altas("S-1")[0]["alta_id"] == doc["alta_id"]

    repo.save_operation({"operation_id": "OP-20260101-AAAAAAAAAAAA", "operator": "ci"})
    assert repo.list_operations(operator="ci")[0]["operation_id"] == "OP-20260101-AAAAAAAAAAAA"


def test_transactions_prevent_double_booking(emulator_repo):
    from backend.repository import ConflictError

    def attempt(n):
        try:
            emulator_repo.reserve(["10.20.38.9"], f"S-{n}", "ci", f"OP-{n}")
            return "ok"
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count("ok") == 1
