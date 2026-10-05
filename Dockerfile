FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8080 \
    LOG_DIR= \
    LOG_FORMAT=json

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY config ./config
COPY data/ejemplo_inventario_ips.xlsx ./data/ejemplo_inventario_ips.xlsx

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD \
  python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", os.environ[\"APP_PORT\"])}/api/health', timeout=4)"

# Cloud Run inyecta PORT; en otros entornos se usa APP_PORT.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host ${APP_HOST} --port ${PORT:-${APP_PORT}} --proxy-headers --forwarded-allow-ips='*'"]
