"""Punto de entrada de Claro CENAM Service Manager (``uvicorn backend.main:app``).

La persistencia vive en Cloud Firestore (``backend.repositories``). El Excel solo
se usa como formato de importación/exportación del inventario de IPs.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__ as APP_VERSION
from .api.dependencies import build_state
from .api.errors import register_exception_handlers
from .api.middleware import operation_tracing
from .api.routes import api_router
from .core import tracing
from .core.settings import BASE_DIR, get_settings

logger = logging.getLogger("claro.api")

FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tracing.configure_logging(settings)
    if not hasattr(app.state, "claro"):
        app.state.claro = build_state(settings)
    logger.info("Aplicación iniciada", extra={"version": APP_VERSION, "backend": app.state.claro.backend,
                                               "env": settings.app_env})
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="Claro CENAM - Service Manager", version=APP_VERSION, lifespan=lifespan)
    application.middleware("http")(operation_tracing)
    register_exception_handlers(application)
    application.include_router(api_router)
    # El frontend estático se monta al final para no tapar las rutas /api.
    if FRONTEND_DIR.is_dir():
        application.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("backend.main:app", host=settings.app_host, port=settings.app_port)
