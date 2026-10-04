@echo off
chcp 65001 > nul
title Claro CENAM - Service Manager
cd /d "%~dp0"
echo ========================================================
echo   CLARO CENAM - SERVICE MANAGER ^& GENERADOR DE ALTAS
echo ========================================================
echo.

where python > nul 2>&1
if errorlevel 1 (
  echo [ERROR] No se encontro Python 3.11+ en el PATH. Instalelo desde python.org.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual...
  python -m venv .venv || goto :error
)

echo Instalando/actualizando dependencias...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :error

if not exist ".env" (
  echo [AVISO] No existe el archivo .env. Copie .env.example a .env y configure Firebase.
  echo         Iniciando en modo demostracion (datos en memoria^).
  set DATA_BACKEND=memory
)

echo Iniciando servidor en http://localhost:8000 ...
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
pause
exit /b 0

:error
echo [ERROR] No se pudo preparar el entorno. Revise el mensaje anterior.
pause
exit /b 1
