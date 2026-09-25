# Claro CENAM Service Manager

Aplicación local para consultar un inventario de direcciones IP en Excel, reservar una IP disponible y generar el formato técnico de alta de un servicio.

## Requisitos

- Python 3.11 o superior
- Un archivo `.xlsx` con las subredes organizadas en pares de columnas: octeto y etiqueta

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

En Windows, activa el entorno con `.venv\Scripts\activate`.

## Ejecución

```bash
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Abre `http://127.0.0.1:8000`. El servidor escucha únicamente en la máquina local por defecto.

## Pruebas

```bash
python -m pytest
```

## Seguridad y operación

- Solo se admiten archivos `.xlsx` de hasta 10 MB.
- El inventario cargado se guarda como `data/inventario_activo.xlsx` y no se versiona.
- La reserva vuelve a validar que la IP siga libre antes de escribir y serializa las modificaciones dentro del proceso.
- La aplicación no implementa autenticación. No debe exponerse a Internet ni a una red compartida sin incorporar control de acceso, auditoría y persistencia transaccional.
- El Excel de ejemplo contiene únicamente datos ficticios. No deben versionarse credenciales, datos personales ni inventarios operativos.

## Estructura

- `backend/`: API FastAPI, parser de Excel y generador de formato.
- `frontend/`: interfaz estática servida por FastAPI.
- `data/`: generador y Excel de demostración.
- `tests/`: pruebas del parser, formato y API HTTP.
