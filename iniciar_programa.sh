#!/usr/bin/env bash
# Inicio local en macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
if [ ! -x .venv/bin/python ]; then
  echo "Creando entorno virtual..."
  "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt

if [ ! -f .env ]; then
  echo "[AVISO] No existe .env: iniciando en modo demostración (datos en memoria)."
  export DATA_BACKEND=memory
fi

PORT=${APP_PORT:-8000}
echo "Servidor en http://127.0.0.1:${PORT}"
exec .venv/bin/python -m uvicorn backend.app:app --host "${APP_HOST:-127.0.0.1}" --port "$PORT"
