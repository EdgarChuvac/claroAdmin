# Arquitectura y modelo de datos

## Propósito

Claro CENAM Service Manager es una aplicación web interna para administrar inventario de direcciones IP, reservar y liberar direcciones por servicio, consultar la topología de transporte y generar formatos de alta para servicios de INTERNET y DATOS. Los datos se guardan en Cloud Firestore; para desarrollo y demostraciones se puede usar un cliente en memoria compatible.

Este documento resume la arquitectura actual del código y presenta dos vistas complementarias: un diagrama de clases de los componentes principales y un diagrama entidad-relación del dominio. Las relaciones del diagrama ER son relaciones lógicas entre documentos; Firestore no impone claves foráneas.

## Tecnologías y organización

- **Interfaz:** HTML, CSS y JavaScript nativo en `frontend/`; FastAPI sirve los archivos estáticos.
- **API:** Python, FastAPI y Pydantic. Los routers se organizan por dominio: sistema, inventario, red, reservas, altas y operaciones.
- **Lógica de aplicación:** servicios de catálogo, topología, importación/exportación Excel y generación de formatos.
- **Persistencia:** `InventoryRepository` centraliza las operaciones sobre Firestore. `FirestoreHandle` permite usar Firestore real o el cliente falso en memoria.
- **Trazabilidad:** las peticiones reciben un identificador `operation_id`; las escrituras registran el operador y los datos de auditoría.

```mermaid
flowchart LR
    U[Usuario] --> FE[Frontend<br/>index.html · app.js · style.css]
    FE -->|HTTP / JSON| API[FastAPI<br/>routers por dominio]
    API --> DEP[Dependencias<br/>AppState · OperatorDep]
    DEP --> SVC[Servicios<br/>catálogo · topología · formatos · Excel]
    DEP --> REPO[InventoryRepository]
    SVC --> REPO
    REPO --> HANDLE[FirestoreHandle]
    HANDLE --> FS[(Cloud Firestore)]
    HANDLE --> MEM[(Firestore falso<br/>modo memoria)]
    API --> TRACE[Middleware y tracing<br/>operation_id · auditoría]
    TRACE --> REPO
```

## Diagrama de clases

El diagrama muestra las dependencias principales y los modelos de entrada que representan los datos enviados por la interfaz. Los routers son módulos con funciones de endpoint, por eso se representan como módulos y no como clases.

```mermaid
classDiagram
    direction LR

    class AppState {
      +Settings settings
      +InventoryRepository repo
      +Catalog catalog
      +str backend
    }

    class Settings {
      +str data_backend
      +str firebase_project_id
      +str firestore_database_id
      +str firestore_collection_prefix
      +str config_dir
    }

    class FirestoreHandle {
      +client
      +transactional
      +descending
      +field_filter
      +str backend
    }

    class InventoryRepository {
      +FirestoreHandle handle
      +reserve(ips, service_id, operator, operation_id)
      +release(ips, service_id, operator, operation_id)
      +register_alta(data)
      +decommission_service(service_id)
      +list_islas()
      +list_vlans(isla)
      +get_ultima_milla_profile(role)
    }

    class Catalog {
      +services
      +NetworkDefaults network_defaults
      +centrales
      +medios
      +regiones
      +service(tipo)
      +medio_ruta(medio)
    }

    class ServiceTemplate {
      +str label
      +str banner
      +str vrf_name
      +str vrf_desc
      +str rd
      +default_items(tipo, velocidad)
    }

    class Medio {
      +str label
      +str ruta
      +bool usa_chasis
      +str demarcador
      +str vrf_gestor
      +str vlan_gestor
    }

    class FormatData {
      +str id_servicio
      +str cliente
      +str medio
      +str region
      +str isla
      +str equipo_cpe
      +str vrf_gestor
      +str vlan_gestor
      +str red_gestor
      +str gw_gestor
      +str ip_gestor_raisecom
      +str loopback
    }

    class EquipmentData {
      +str rol
      +str marca
      +str modelo
      +str hostname
      +str ip_admon
      +str lado
    }

    class ImportResult {
      +str import_id
      +str mode
      +list sheets
      +int segments
      +int ips_written
      +list conflicts
      +to_dict()
    }

    class GenerateFormatRequest {
      +FormatData data
    }

    class AltaRequest {
      +FormatData data
    }

    class RouteModules {
      system
      inventory
      network
      reservations
      altas
      operations
    }

    AppState --> Settings : configuración
    AppState --> Catalog : catálogo cargado
    AppState --> InventoryRepository : repositorio
    InventoryRepository --> FirestoreHandle : persistencia
    Catalog o-- ServiceTemplate : plantillas
    Catalog o-- Medio : medios disponibles
    FormatData o-- EquipmentData : equipos de ruta
    GenerateFormatRequest --> FormatData
    AltaRequest --> FormatData
    RouteModules ..> AppState : dependencias de API
    InventoryRepository ..> ImportResult : resultado de importación
```

## Diagrama entidad-relación

El inventario de IP y los registros del servicio son el núcleo transaccional. La topología, los equipos y las VLAN complementan la información usada para construir el formato. Los nombres entre paréntesis señalan colecciones o rutas conocidas de Firestore.

```mermaid
erDiagram
    INVENTORY_SHEET ||--o{ IP_SEGMENT : contiene
    ISLA ||--o{ INVENTORY_SHEET : organiza
    ISLA ||--o{ CHASIS : agrupa
    ISLA ||--o{ VLAN_CONFIG : identifica
    IP_SEGMENT ||--o{ IP_ADDRESS : contiene
    SERVICE ||--o{ IP_ADDRESS : reserva
    SERVICE ||--o| LOOPBACK : puede_tener
    SERVICE ||--o{ ALTA : registra
    ALTA ||--o| ALTA_HASH : indexa
    SERVICE ||--o{ OPERATION : queda_auditado
    OPERATION ||--o{ IP_ADDRESS : modifica
    ISLA ||--o{ RADIO : dispone
    ISLA ||--o{ GPON : dispone
    RADIO }o--o{ TRANSMISSION_EQUIPMENT : compone_ruta
    GPON }o--o{ TRANSMISSION_EQUIPMENT : compone_ruta
    LAST_MILE_PROFILE ||--o{ LAST_MILE_EQUIPMENT : describe

    INVENTORY_SHEET {
      string id "inventory_sheets/{red_base}"
      string sheet "red base /24"
      string isla "central asociada, opcional"
    }
    IP_SEGMENT {
      string id "ip_segments/{segment_id}"
      string sheet "referencia lógica a hoja"
      string isla "isla asociada, opcional"
      string network_ip
      string cidr
      string gateway_ip
      string vlan
    }
    IP_ADDRESS {
      string id "ip_addresses/{ip}"
      string ip
      string segment_id
      string status "DISPONIBLE, OCUPADA o GATEWAY"
      string service_id "vacío si no está asignada"
      string assigned_operation_id
    }
    SERVICE {
      string id "identificador de servicio"
      string cliente
      string estado
    }
    LOOPBACK {
      string id "loopbacks/{ip}"
      string ip "dirección /32"
      string service_id
      string estado
    }
    ALTA {
      string id "altas/{id}"
      string service_id
      string texto
      string estado "ACTIVA o BAJA"
      string operation_id
    }
    ALTA_HASH {
      string id "alta_hashes/{sha256}"
      string alta_id
      string service_id
    }
    OPERATION {
      string id "operations/{operation_id}"
      string operation_id
      string operator
      string action
      string service_id
      datetime created_at
    }
    ISLA {
      string id "islas/{slug}"
      string nombre
      string region
      boolean activo
    }
    CHASIS {
      string id "chasis/{id}"
      string isla_id
      string nombre
      string slots
      string puertos
    }
    VLAN_CONFIG {
      string id "vlans/{isla}_{vlan} o ruta anidada"
      string isla
      string vlan
      string rd
      string vrf_name
      string vrf_desc
      string vlan_desc
      string config
    }
    RADIO {
      string id "radio/{id}"
      string isla
      string nombre
      string equipos_ruta
    }
    GPON {
      string id "g-pon/{id}"
      string isla_id
      string nombre
      string equipos_ruta
    }
    TRANSMISSION_EQUIPMENT {
      string id "Equipos_Transmision/{...}"
      string no
      string rol
      string marca
      string modelo
      string hostname
      string ip_admon
    }
    LAST_MILE_PROFILE {
      string id "ultima_milla/{mc|ont|radio}"
      string rol
      string marca
      string modelo
      string vrf_gestor
      string vlan_gestor
      string red_gestor
      string gw_gestor
      string ip_gestor_raisecom
    }
    LAST_MILE_EQUIPMENT {
      string id "ultima_milla/{rol}/{marca}/{modelo}"
      string rol
      string marca
      string modelo
      string ip_admon
      string lado
    }
```

### Lectura del modelo

- **Inventario:** una hoja `/24` agrupa subredes; cada subred contiene direcciones IP. La dirección guarda su estado y, si está ocupada, el identificador del servicio.
- **Servicio y alta:** `SERVICE` es una entidad lógica identificada por `service_id`, no una colección central independiente. Ese identificador enlaza reservas, loopback, altas y operaciones. El alta guarda el texto generado y su estado; el hash permite detectar duplicados.
- **Topología:** una isla/central organiza hojas, segmentos, chasis y equipos de acceso. Radio y G-PON pueden referenciar equipos de transmisión que forman la ruta impresa.
- **VLAN:** su configuración se asocia a isla y número de VLAN, y puede estar en la estructura plana o en la estructura anidada compatible con Firestore.
- **Última milla:** los perfiles de MC, ONT y Radio suministran valores de gestión por rol; los documentos de equipos contienen marca, modelo e IP de administración. El CPE/FW se cataloga por rol, marca y modelo.
- **Auditoría:** `operation_id` identifica una petición y permite relacionar sus cambios con el operador, el servicio y las direcciones afectadas.

## Flujo típico de generación y registro de un alta

1. La interfaz consulta catálogos de islas, medios, equipos, VLAN y direcciones disponibles.
2. El operador selecciona el servicio y completa los datos; la API valida la carga mediante modelos Pydantic.
3. La API combina la carga con plantillas y datos de topología para generar una vista previa del formato.
4. Al registrar el alta, el repositorio persiste el formato y aplica en una transacción las asignaciones relacionadas que correspondan, como loopback e IPs.
5. El middleware asigna `operation_id` y registra la auditoría. Los errores de API también conservan ese identificador para facilitar su rastreo.

## Referencias del código

- Entrada y montaje de la aplicación: `backend/main.py`.
- Estado y dependencias de FastAPI: `backend/api/dependencies.py`.
- Modelos de entrada: `backend/schemas/requests.py`.
- Acceso a datos y operaciones de dominio: `backend/repositories/inventory.py`.
- Catálogo y valores predeterminados: `backend/services/catalog.py` y `config/`.
- Generación del formato: `backend/services/format_generator.py`.
- Interfaz: `frontend/index.html`, `frontend/app.js` y `frontend/style.css`.
