# AGENTS.md — Contexto para agentes de IA

Guía corta para que un agente (Claude, Copilot, Cursor, Codex…) pueda trabajar en este repositorio sin
romper nada. Los detalles están en [README.md](README.md) (despliegue),
[docs/MANUAL_DESARROLLADOR.md](docs/MANUAL_DESARROLLADOR.md) (arquitectura y API) y
[docs/MANUAL_USUARIO.md](docs/MANUAL_USUARIO.md) (uso de la pantalla).

## 1. Qué es

**Claro CENAM Service Manager**: aplicación web interna para ingenieros de Claro que

* administra el **inventario de IPs** (segmentos /24 → subredes → IPs) en **Cloud Firestore**,
* **reserva y libera** IPs por ID de servicio,
* genera el **formato de alta** (texto para INTERNET o DATOS corporativo) y lo registra,
* deja **trazabilidad**: cada petición tiene un `operation_id` (`OP-AAAAMMDD-XXXXXXXXXXXX`) que aparece en la
  pantalla, en los logs y en la colección `operations`.

No hay inicio de sesión: el usuario escribe su nombre y viaja en el header `X-Operator`. Toda escritura lo exige.

Idioma: **español** en la interfaz, los mensajes de error, los docs y los commits.

## 2. Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11+ (probado con 3.12), FastAPI, Pydantic 2, pydantic-settings, Uvicorn |
| Datos | Cloud Firestore (`firebase-admin`, `google-cloud-firestore`); cliente en memoria para pruebas/demo |
| Excel | openpyxl (solo importar/exportar; Firestore es la fuente de verdad) |
| Frontend | HTML + CSS + JavaScript nativo en `frontend/`, **sin build ni npm**; lo sirve el mismo FastAPI |
| Pruebas / lint | pytest, httpx (TestClient), ruff |

Versiones exactas: `requirements.txt` (producción) y `requirements-dev.txt` (incluye la anterior + pruebas).

## 3. Restaurar dependencias y arrancar

```bash
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt    # producción/Docker: requirements.txt
cp .env.example .env                   # luego completar (ver sección 4)
```

* **No hace falta Node ni npm.** El frontend no se compila.
* **Arrancar sin credenciales (modo demo, datos en memoria con el Excel de ejemplo):**

  ```bash
  DATA_BACKEND=memory LOG_DIR= python -m uvicorn backend.main:app --reload
  ```

  Abrir `http://127.0.0.1:8000` (Swagger en `/docs`). Los datos se pierden al reiniciar.
* **Usuarios finales:** `iniciar_programa.bat` (Windows) o `./iniciar_programa.sh` crean `.venv`, instalan
  `requirements.txt` y arrancan. Sin `.env` arrancan en modo memoria.
* **Docker / Cloud Run:** `docker build -t claro-admin .` — el contenedor escucha en `PORT` o `APP_PORT` (8080).
* **Emulador de Firestore (opcional):** requiere Java 11+ y `npm i -g firebase-tools`:
  `firebase emulators:start --only firestore --project demo-claro-admin`.

## 4. Variables de entorno

Se leen de variables de entorno o de `.env` en la raíz (`backend/core/settings.py`; nombre en mayúsculas del
atributo). **Nunca** versione `.env` ni credenciales: `.gitignore` ya los excluye y **el repositorio es público**.

### Esenciales

| Variable | Cuándo | Valor |
|---|---|---|
| `DATA_BACKEND` | siempre | `firestore` (por defecto) o `memory`. **Si es `firestore` y faltan credenciales, la app no arranca.** Para desarrollo y pruebas use `memory` |
| `FIREBASE_PROJECT_ID` | con `firestore` | ID del proyecto (se deduce del JSON de credenciales si no se define) |
| Credenciales (una de tres) | con `firestore` | `FIREBASE_CREDENTIALS_FILE` (ruta al JSON de la cuenta de servicio), `FIREBASE_CREDENTIALS_JSON` (JSON o Base64) o credenciales por defecto de Google (Cloud Run / `gcloud auth application-default login`) |
| `MONITOREO_PSK` | producción, si las altas llevan loopback | PRE-SHARED KEY que se imprime en el bloque *FAVOR DE AGREGAR LOOPBACK AL MONITOREO EN NMIS E ISE*. Sin ella la línea sale vacía. **Es un secreto: no la escriba en código, config ni docs** |
| `APP_ENV` | producción | `production` (`development` por defecto, `test` en pytest) |

### Opcionales (con valor por defecto)

`APP_HOST` (`127.0.0.1`), `APP_PORT` (`8000`), `MAX_UPLOAD_MB` (`10`), `MEMORY_SEED_SAMPLE` (`true`),
`FIRESTORE_DATABASE_ID` (`(default)`), `FIRESTORE_COLLECTION_PREFIX` (vacío; preferir otra base por ambiente),
`FIRESTORE_EMULATOR_HOST` (vacío; `127.0.0.1:8085` con el emulador), `LOG_LEVEL` (`INFO`), `LOG_FORMAT`
(`json`), `LOG_DIR` (`logs`; **vacío = solo consola**, recomendado en desarrollo y contenedores),
`LOG_FILE_MAX_MB` (`10`), `LOG_FILE_BACKUPS` (`10`), `PERSIST_READ_OPERATIONS` (`false`),
`OPERATIONS_RETENTION_DAYS` (`365`), `CONFIG_DIR` (`config/`). En Cloud Run, `PORT` tiene prioridad sobre `APP_PORT`.

Las pruebas fijan solas `DATA_BACKEND=memory`, `LOG_DIR=` y `APP_ENV=test` (`tests/conftest.py`) y nunca usan
credenciales reales.

## 5. Comandos de verificación (correr antes de cada commit)

```bash
ruff check backend scripts tests      # lint (config en pyproject.toml)
python -m pytest                      # ~60 pruebas, <2 s, sin red ni credenciales
FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 python -m pytest tests/integration   # solo con el emulador
node --check frontend/app.js          # si tocó el JS y tiene Node; opcional
```

No hay CI configurado: estas verificaciones son responsabilidad de quien hace el cambio.

## 6. Estructura y dónde va cada cambio

```
backend/                     paquete Python; entrada: backend.main:app
  main.py                    create_app(): lifespan, middleware, errores, routers, frontend estático
  api/
    dependencies.py          AppState, build_state(), StateDep / OperatorDep, helpers de validación
    middleware.py            operation_id por petición + auditoría en `operations`
    errors.py                errores -> JSON con operation_id
    routes/                  system, inventory, network (islas/VLAN/loopbacks), reservations, altas, operations
  schemas/requests.py        modelos Pydantic de entrada (extra="forbid")
  core/                      settings.py, tracing.py, errors.py (InventoryError, NotFoundError, ConflictError)
  db/                        firebase_client.py, firestore_fake.py (cliente en memoria)
  repositories/inventory.py  TODO el acceso a Firestore
  services/                  catalog, format_generator, excel_parser, excel_import, excel_export
config/                      service_templates.json, centrales.json (se leen al arrancar)
frontend/                    index.html, app.js, style.css
firebase/                    firestore.rules, firestore.indexes.json (firebase.json en la raíz)
scripts/                     python -m scripts.import_excel | seed_centrales | create_sample_excel
tests/                       unit/ (sin HTTP) · api/ (TestClient en memoria) · integration/ (emulador)
data/                        ejemplo_inventario_ips.xlsx (carga automática en modo memoria)
docs/                        manuales de usuario y desarrollador
```

| Quiero… | Toque… |
|---|---|
| Un endpoint nuevo | el router del dominio en `backend/api/routes/` (o un módulo nuevo registrado en `routes/__init__.py`) + modelo en `schemas/requests.py` |
| Lógica de negocio | `backend/services/` (sin FastAPI) |
| Leer/escribir Firestore | `backend/repositories/inventory.py`; si usa una operación nueva del SDK, implementarla también en `backend/db/firestore_fake.py` |
| Cambiar el texto del alta | `backend/services/format_generator.py` + pruebas en `tests/unit/` |
| Plantillas, medios, pool de loopbacks | `config/service_templates.json` (reiniciar la app) |
| Pantalla | `frontend/index.html` + `frontend/app.js` (+ `style.css`) |
| Una consulta con `where` + `order_by` en campos distintos | agregar el índice en `firebase/firestore.indexes.json` |

## 7. Conceptos de dominio

* **Segmento /24** (`inventory_sheets`): equivale a una pestaña del Excel histórico; se nombra por su red base (`10.20.38.0`).
* **Subred** (`ip_segments`): bloque dentro del /24 con red, gateway, broadcast y **VLAN**.
* **IP** (`ip_addresses/{ip}`): estado `DISPONIBLE`, `OCUPADA` (con `service_id`) o `GATEWAY`.
* **Isla / Central**: agrupa segmentos (campo `isla`). Flujo de la pantalla Equipamiento:
  **Isla → Tipo de servicio → VLAN → Segmento /24 → Subred → IP**.
* **VLAN** (`vlans/{ISLA}_{vlan}`): guarda RD, nombre/descripción de VRF y descripción de VLAN para autocompletar.
* **Loopback** (`loopbacks/{ip}`): /32 asignada automáticamente del pool `10.212.100.1`–`.254`, una por servicio.
* **Alta** (`altas`): texto final registrado; idempotente por hash del texto (`alta_hashes`).
* **Factibilidad**: texto pegado por el usuario o la marca «Sin factibilidad»; sin una de las dos no se registra el alta.
* **Tipos de servicio**: solo `INTERNET` y `DATOS` (solo INTERNET usa IP pública).

## 8. Reglas que no se deben romper

1. **Secretos fuera del repo**: credenciales, `.env`, `MONITOREO_PSK`. El repo es público.
2. **Escrituras atómicas**: reservas, liberaciones, loopbacks y altas usan transacciones de Firestore.
   Dentro de una transacción **todas las lecturas van antes de cualquier escritura**.
3. **Toda escritura requiere operador** (`OperatorDep`) y debe auditarse con `tracing.audit(...)`.
4. **Las respuestas de error conservan el `operation_id`**: lance `InventoryError`/`NotFoundError`/`ConflictError`
   (o `HTTPException`); no devuelva errores a mano.
5. **El formato de alta imprime solo lo que se llenó**: una línea con valor vacío no aparece.
6. **La importación `merge` nunca pisa IPs ocupadas en Firestore**; los conflictos se reportan.
7. **`form_data` de un alta nunca guarda la PSK.**
8. **Compatibilidad del cliente en memoria**: si el repositorio usa algo nuevo del SDK de Firestore,
   `firestore_fake.py` debe soportarlo; si no, las pruebas pasan pero producción falla (o al revés).
9. Mantener el frontend **sin dependencias ni build**.

## 9. Trampas conocidas

* `DATA_BACKEND` por defecto es `firestore`: sin credenciales, `uvicorn` falla al arrancar. Use `memory`.
* `LOG_DIR` por defecto escribe en `logs/`; en contenedores o pruebas déjelo vacío.
* `get_settings()` y `default_catalog()` están cacheados (`lru_cache`): en pruebas use `get_settings.cache_clear()`.
* Los segmentos importados antes de la versión 2.1 no tienen isla: aparecen como «Segmentos sin isla asignada».
* Las capturas en `docs/img` son de la versión 2.0 (la pantalla cambió en 2.1).
* Las loopbacks no se liberan solas al dar de baja un servicio (se borra el documento `loopbacks/{ip}`).
* `scripts/create_sample_excel.py` regenera `data/ejemplo_inventario_ips.xlsx`; varias pruebas dependen de ese archivo.

## 10. Git

* Rama principal: `master` (también existe `featute/forms`, más antigua).
* Commits en español, describiendo el porqué. Correr la sección 5 antes de hacer push.
