import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Las pruebas nunca usan credenciales reales.
os.environ.setdefault("DATA_BACKEND", "memory")
os.environ.setdefault("LOG_DIR", "")
os.environ.setdefault("LOG_FORMAT", "json")
os.environ.setdefault("APP_ENV", "test")
for var in ("FIREBASE_CREDENTIALS_JSON", "FIREBASE_CREDENTIALS_FILE"):
    os.environ.pop(var, None)

SAMPLE_XLSX = ROOT / "data" / "ejemplo_inventario_ips.xlsx"
OPERATOR = {"X-Operator": "Operador%20Prueba"}


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import main as app_module
    from backend.core.settings import get_settings

    monkeypatch.setenv("DATA_BACKEND", "memory")
    get_settings.cache_clear()
    if hasattr(app_module.app.state, "claro"):
        del app_module.app.state.claro
    with TestClient(app_module.app) as test_client:
        yield test_client
    del app_module.app.state.claro
    get_settings.cache_clear()


@pytest.fixture
def repo(client):
    return client.app.state.claro.repo
