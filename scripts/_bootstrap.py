"""Inicializa configuración, logs y repositorio para scripts de línea de comandos."""

from backend.api.dependencies import build_state
from backend.core import tracing
from backend.core.settings import get_settings


def bootstrap(operator: str):
    settings = get_settings()
    tracing.configure_logging(settings)
    ctx = tracing.OperationContext(operation_id=tracing.new_operation_id(), method="CLI",
                                   path="scripts", operator=operator)
    tracing.set_context(ctx)
    return build_state(settings), ctx
