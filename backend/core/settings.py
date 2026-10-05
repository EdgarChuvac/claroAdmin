"""Configuración de la aplicación leída exclusivamente desde variables de entorno.

Todas las variables pueden definirse en el entorno del sistema operativo, en el
servicio (systemd, Docker, Cloud Run) o en un archivo ``.env`` en la raíz del
proyecto. Consulte ``.env.example`` para la lista completa y su significado.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aplicación -----------------------------------------------------
    app_env: Literal["development", "production", "test"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    max_upload_mb: int = Field(default=10, ge=1, le=50)

    # --- Persistencia ---------------------------------------------------
    # "firestore": Cloud Firestore real o emulador.
    # "memory": base en memoria para pruebas y demostraciones (se pierde al reiniciar).
    data_backend: Literal["firestore", "memory"] = "firestore"
    memory_seed_sample: bool = True

    # --- Firebase / Firestore -------------------------------------------
    firebase_project_id: str = ""
    # Ruta a un JSON de cuenta de servicio.
    firebase_credentials_file: str = ""
    # Contenido del JSON de cuenta de servicio (texto JSON o Base64).
    firebase_credentials_json: str = ""
    firestore_database_id: str = "(default)"
    # Prefijo para todas las colecciones (p. ej. "qa_" para separar ambientes).
    firestore_collection_prefix: str = ""
    # Si se define, el SDK se conecta al emulador local (p. ej. 127.0.0.1:8085).
    firestore_emulator_host: str = ""

    # --- Trazabilidad / logs --------------------------------------------
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    log_dir: str = "logs"
    log_file_max_mb: int = Field(default=10, ge=1)
    log_file_backups: int = Field(default=10, ge=0)
    # Guardar también las consultas (GET) en la colección de operaciones.
    persist_read_operations: bool = False
    # Días que se conserva cada operación (campo expires_at para la política TTL).
    operations_retention_days: int = Field(default=365, ge=1)

    # --- Catálogos ------------------------------------------------------
    config_dir: str = str(BASE_DIR / "config")
    # PRE-SHARED KEY que se imprime en el bloque de monitoreo (NMIS e ISE) de cada alta.
    monitoreo_psk: str = ""

    @field_validator("firestore_collection_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        value = value.strip()
        if value and not all(ch.isalnum() or ch in "_-" for ch in value):
            raise ValueError("FIRESTORE_COLLECTION_PREFIX solo admite letras, números, '_' y '-'.")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_level(cls, value: str) -> str:
        value = value.upper().strip()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL inválido.")
        return value

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def log_path(self) -> Path:
        path = Path(self.log_dir)
        return path if path.is_absolute() else BASE_DIR / path

    def firebase_credentials_info(self) -> dict[str, Any] | None:
        """Devuelve el JSON de la cuenta de servicio si se configuró en línea."""
        raw = self.firebase_credentials_json.strip()
        if not raw:
            return None
        if not raw.startswith("{"):
            try:
                raw = base64.b64decode(raw).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError(
                    "FIREBASE_CREDENTIALS_JSON debe ser JSON o JSON codificado en Base64."
                ) from exc
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("FIREBASE_CREDENTIALS_JSON no contiene un JSON válido.") from exc
        if info.get("type") != "service_account":
            raise ValueError("FIREBASE_CREDENTIALS_JSON no es una cuenta de servicio.")
        return info


@lru_cache
def get_settings() -> Settings:
    return Settings()
