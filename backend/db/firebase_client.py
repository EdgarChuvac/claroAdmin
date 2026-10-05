"""Creación del cliente de Firestore a partir de las variables de entorno."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from ..core.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class FirestoreHandle:
    client: Any
    transactional: Callable[[Callable[..., Any]], Callable[..., Any]]
    descending: str
    field_filter: Callable[[str, str, Any], Any]
    backend: str


class _SimpleFilter:
    def __init__(self, field_path: str, op_string: str, value: Any):
        self.field_path = field_path
        self.op_string = op_string
        self.value = value


def create_memory_handle() -> FirestoreHandle:
    from . import firestore_fake

    return FirestoreHandle(
        client=firestore_fake.FakeFirestoreClient(),
        transactional=firestore_fake.transactional,
        descending=firestore_fake.DESCENDING,
        field_filter=_SimpleFilter,
        backend="memory",
    )


def create_firestore_handle(settings: Settings) -> FirestoreHandle:
    """Inicializa Firebase Admin / Firestore.

    Orden de resolución de credenciales:

    1. ``FIRESTORE_EMULATOR_HOST`` → emulador local, sin credenciales.
    2. ``FIREBASE_CREDENTIALS_JSON`` → JSON (o Base64) de cuenta de servicio.
    3. ``FIREBASE_CREDENTIALS_FILE`` → ruta a JSON de cuenta de servicio.
    4. Credenciales por defecto de Google (Cloud Run, GCE, ``gcloud auth``).
    """
    from google.cloud import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter

    database = settings.firestore_database_id or "(default)"

    if settings.firestore_emulator_host:
        os.environ["FIRESTORE_EMULATOR_HOST"] = settings.firestore_emulator_host
        project = settings.firebase_project_id or "demo-claro-admin"
        client = firestore.Client(project=project, database=database)
        logger.info("Conectado al emulador de Firestore", extra={"emulator": settings.firestore_emulator_host})
    else:
        import firebase_admin
        from firebase_admin import credentials
        from firebase_admin import firestore as admin_firestore

        info = settings.firebase_credentials_info()
        if info is not None:
            cred = credentials.Certificate(info)
        elif settings.firebase_credentials_file:
            if not os.path.isfile(settings.firebase_credentials_file):
                raise RuntimeError(
                    f"FIREBASE_CREDENTIALS_FILE no existe: {settings.firebase_credentials_file}"
                )
            cred = credentials.Certificate(settings.firebase_credentials_file)
        else:
            cred = credentials.ApplicationDefault()

        options: dict[str, Any] = {}
        project = settings.firebase_project_id or (info or {}).get("project_id", "")
        if project:
            options["projectId"] = project
        try:
            app = firebase_admin.get_app()
        except ValueError:
            app = firebase_admin.initialize_app(cred, options)
        client = admin_firestore.client(app=app, database_id=database)
        logger.info(
            "Conectado a Cloud Firestore",
            extra={"project": project or "(credenciales por defecto)", "database": database},
        )

    return FirestoreHandle(
        client=client,
        transactional=firestore.transactional,
        descending=firestore.Query.DESCENDING,
        field_filter=lambda field, op, value: FieldFilter(field, op, value),
        backend="firestore",
    )
