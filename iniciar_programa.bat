@echo off
chcp 65001 > nul
title Claro CENAM - Service Manager & Generador de Altas
echo ========================================================
echo   CLARO CENAM - SERVICE MANAGER & GENERADOR DE ALTAS
echo ========================================================
echo.
echo Iniciando servidor local en http://localhost:8000 ...
echo Abriendo navegador web...
echo.

start "" http://localhost:8000
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
pause
