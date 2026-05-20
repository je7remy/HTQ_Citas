
# SGCM — Sistema Web de Gestión de Citas Médicas

[![CI](https://img.shields.io/github/actions/workflow/status/je7remy/HTQ_Citas/ci.yml?branch=main&label=CI&logo=github)](https://github.com/je7remy/HTQ_Citas/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-24+-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-Académico-lightgrey.svg)](#)

Plataforma web para automatizar y optimizar el proceso de gestión de citas médicas del **Hospital Regional Traumatológico y Quirúrgico Prof. Juan Bosch (HTQPJB)** en La Vega, República Dominicana.

> Trabajo de grado para optar por el título de Licenciatura en Informática — Universidad Nacional Pedro Henríquez Ureña (UNPHU), Recinto La Vega.

---

## Tabla de contenido

- [Sobre el proyecto](#sobre-el-proyecto)
- [Características principales](#caracter%C3%ADsticas-principales)
- [Arquitectura](#arquitectura)
- [Stack tecnológico](#stack-tecnol%C3%B3gico)
- [Evolución del stack tecnológico](#evoluci%C3%B3n-del-stack-tecnol%C3%B3gico)
- [Inicio rápido](#inicio-r%C3%A1pido)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Casos de uso](#casos-de-uso)
- [Roles y permisos](#roles-y-permisos)
- [Endpoints REST](#endpoints-rest)
- [Variables de entorno](#variables-de-entorno)
- [Migraciones de base de datos](#migraciones-de-base-de-datos)
- [Pruebas automatizadas](#pruebas-automatizadas)
- [Integración continua](#integraci%C3%B3n-continua)
- [Comandos útiles](#comandos-%C3%BAtiles)
- [Documentación](#documentaci%C3%B3n)
- [Respaldos del sistema](#respaldos-del-sistema)
- [Operación sin internet (offline)](#operaci%C3%B3n-sin-internet-offline)
- [Cumplimiento legal](#cumplimiento-legal)
- [Autores](#autores)
- [Versión](#versi%C3%B3n)

---

## Sobre el proyecto

El SGCM automatiza el proceso de gestión de citas que el HTQPJB realizaba previamente con registros físicos, libretas y comunicación verbal. La plataforma reemplaza esos soportes manuales por una solución digital centralizada que opera en la intranet del hospital.

**Lo que el sistema NO es:** una reingeniería del proceso institucional. La lógica operativa, los roles y las responsabilidades del personal se conservan.

**Lo que el sistema SÍ es:** la automatización de los puntos del flujo donde los soportes manuales generaban duplicaciones, demoras y descoordinación.

---

## Características principales

- Autenticación JWT con hashing bcrypt y expiración configurable.
- Control de acceso basado en roles (RBAC) en dos capas: backend y frontend.
- Calendario interactivo con FullCalendar.js, vista mensual por defecto.
- Prevención física de duplicaciones mediante índice único parcial en PostgreSQL.
- Bloqueo temporal del registro de consulta: el médico no puede registrar diagnósticos antes de la fecha de la cita.
- Vinculación de usuarios con perfiles de médico desde la UI del administrador.
- Reset de contraseña por administrador (sin requerir la contraseña anterior; auditado).
- Reportes PDF generados con WeasyPrint, con fecha de emisión y numeración secuencial.
- Reportes administrativos: resumen y PDF de usuarios por rol, detalle y PDF de médicos activos con estadísticas.
- Agenda extendida para secretaria/admin con filtros por médico, rango de fechas, estado y especialidad; exportación a PDF y Excel; impresión optimizada (`@media print`).
- Sistema de respaldos (CU-16) con tres modalidades: local, externo (USB/UNC) y andamiaje preparado para nube (Amazon S3, Google Cloud Storage, Azure Blob).
- Auditoría transaccional de todas las operaciones críticas (Ley 172-13).
- Suite de pruebas automatizadas con pytest.
- CI/CD con GitHub Actions ejecutando linter, tests y construcción de imagen Docker.
- Despliegue contenedorizado con Docker Compose.
- Máscaras visuales en cédula y teléfono para mejor experiencia de usuario.

---

## Arquitectura

```mermaid
flowchart TB
    Browser[Navegador del usuario]
    subgraph Server["Servidor en intranet del hospital"]
        Nginx[Nginx<br/>puerto 80<br/>proxy + estaticos]
        API[FastAPI<br/>puerto 8000<br/>backend]
        DB[(PostgreSQL<br/>puerto 5432<br/>base de datos)]
    end

    Browser -->|HTTP| Nginx
    Nginx -->|/api/v1/*| API
    Nginx -->|archivos HTML/JS/CSS| Browser
    API <-->|SQL| DB
````

---

## Stack tecnológico

### Backend

- **Python 3.11+** — Lenguaje principal.
- **FastAPI** — Framework web asíncrono con OpenAPI automático.
- **SQLModel** — ORM combinado con validación Pydantic.
- **Alembic** — Migraciones versionadas del esquema.
- **python-jose** — Generación y validación de JWT.
- **passlib + bcrypt** — Hashing seguro de contraseñas.
- **WeasyPrint** — Generación de PDFs desde HTML/CSS.
- **pytest + httpx** — Pruebas automatizadas.

### Base de datos

- **PostgreSQL 15** — Con índices únicos parciales para prevenir duplicaciones.

### Frontend

- **HTML5 + JavaScript ES6** — Vanilla, sin framework.
- **Tailwind CSS** — Servido localmente desde `static/vendor/tailwind/`.
- **FullCalendar.js 6.1.15** — Calendario interactivo (también local).
- **Lucide Icons** — Iconografía servida desde `static/vendor/lucide/`.
- **Fuente Inter** — Archivos `.woff2` locales (`static/fonts/inter/`).

> **Sin internet:** todas las dependencias del frontend viajan en el repositorio. El sistema funciona completo dentro de la intranet del HTQPJB aunque el servidor no tenga salida a internet. Ver [`docs/OFFLINE.md`](docs/OFFLINE.md).

### Infraestructura

- **Docker + Docker Compose** — Orquestación de contenedores.
- **Nginx** — Proxy inverso y servidor de archivos estáticos.
- **mkcert** — Certificado SSL para HTTPS en intranet.
- **GitHub Actions** — Integración continua.

---

## Evolución del stack tecnológico

El stack actual no fue el original. Durante las fases de análisis y diseño, y a lo largo de las primeras iteraciones de desarrollo, el proyecto evolucionó significativamente conforme fui descubriendo limitaciones de las herramientas iniciales y conociendo alternativas más apropiadas para los requisitos del sistema. Esta sección documenta esa evolución, porque entender por qué algo cambió es tan importante como saber qué se está usando hoy.

### Comparativa: idea inicial vs implementación final

|Componente|Idea inicial|Stack actual|Razón del cambio|
|---|---|---|---|
|Base de datos|SQLite|PostgreSQL 15|SQLite no soporta índices únicos parciales con cláusula WHERE, característica clave del diseño para resolver el conflicto entre cancelación y reagendamiento de citas. Tampoco está pensado para concurrencia real con múltiples secretarias agendando al mismo tiempo.|
|Framework backend|Flask|FastAPI|Flask es minimalista pero requiere construir manualmente validación de datos, documentación OpenAPI y manejo asíncrono. FastAPI lo trae todo de fábrica con Pydantic, genera Swagger automáticamente y ofrece un rendimiento muy superior gracias a Starlette y al soporte nativo de async/await.|
|ORM|SQLAlchemy puro|SQLModel sobre SQLAlchemy y Pydantic|SQLModel unifica los modelos de base de datos con los esquemas de validación en una sola capa. Reduce código duplicado y mantiene la potencia de SQLAlchemy por debajo.|
|Frontend|HTML, JavaScript y Tailwind CSS|Igual, más FullCalendar.js|Se mantuvo el enfoque vanilla por su simplicidad y por evitar la complejidad de un framework para un sistema de este alcance. Se incorporó FullCalendar.js como pieza clave para la visualización del calendario interactivo.|
|Entorno de operación|Servidor local con Docker|Igual|Decisión validada y mantenida. La contenedorización facilita despliegue, reproducibilidad y portabilidad.|
|Control de versiones|Git|Git más GitHub Actions|Se añadió integración continua: cada commit ejecuta tests automatizados y construye la imagen Docker, garantizando que el código en el repositorio siempre sea desplegable.|
|Diseño visual|Draw.io|Draw.io|Se mantiene como herramienta de planificación de diagramas (DFD, casos de uso, MER).|

### Componentes incorporados durante la evolución

Algunos componentes no estaban en la planificación inicial pero se sumaron al darme cuenta de su importancia:

- **Alembic** para migraciones versionadas del esquema de base de datos. Sin él, cualquier cambio de modelo implicaba intervenciones manuales propensas a errores.
- **WeasyPrint** para generación de reportes PDF a partir de HTML y CSS, lo que permite reutilizar templates del frontend para reportes profesionales.
- **python-jose y passlib (bcrypt)** para JWT y hashing de contraseñas. La autenticación inicial se pensó simple, pero al estudiar la Ley 172-13 quedó claro que se requería hashing fuerte y tokens firmados.
- **Nginx** como proxy inverso. Originalmente se contemplaba que FastAPI sirviera todo (API y archivos estáticos), pero al separar responsabilidades se obtuvo mejor rendimiento, terminación SSL más limpia y un punto de entrada único.
- **pytest y httpx** para una suite de pruebas automatizadas. Esto no estaba en el plan original; surgió de la necesidad de evitar regresiones al iterar el sistema.
- **GitHub Actions** para CI/CD. Práctica que adopté tras enfrentar el primer fallo en pruebas que un test automatizado habría evitado.
- **ruff** como linter para análisis estático del código.

### Por qué documentar esta evolución

Porque demuestra dos cosas que considero importantes en cualquier proyecto técnico serio:

1. **El stack no se eligió por moda, sino por requisitos.** Cada cambio respondió a una limitación concreta encontrada durante el desarrollo o a una característica específica que el sistema necesitaba (por ejemplo, los índices únicos parciales de PostgreSQL que SQLite no soporta).
    
2. **El proyecto evolucionó con disciplina.** Cambiar de Flask a FastAPI o de SQLite a PostgreSQL en mitad del desarrollo no es trivial: implicó reescribir partes considerables del código. Fueron decisiones tomadas tempranamente, antes de que el costo del cambio fuera prohibitivo, lo cual es una habilidad fundamental en ingeniería de software.
    

El stack actual no es perfecto ni final. Hay áreas donde reconozco oportunidades de mejora futura (tests end-to-end con Playwright, observabilidad con Prometheus, despliegue con Kubernetes para múltiples instancias), pero corresponden a un alcance mayor al de un trabajo de grado y quedan documentadas como recomendaciones de evolución.

---

## Inicio rápido

### Requisitos previos

- Docker Engine 24+ y Docker Compose v2.
- Git 2.30+.

### Instalación en cuatro pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/je7remy/HTQ_Citas.git sgcm
cd sgcm

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env y configurar JWT_SECRET_KEY (mínimo 32 caracteres)

# 3. Arrancar el sistema
docker compose up -d --build

# 4. Verificar
docker compose ps
```

Acceder a `http://localhost/` en el navegador.

### Credenciales de demostración

El comando `python -m app.scripts.seed_db` (también ejecutable en automático con `SGCM_SEED=true`) crea el siguiente conjunto de cuentas:

|Rol|Email|Contraseña|
|---|---|---|
|Administrador|`admin@htqpjb.gob.do`|`Admin123!`|
|Secretaria|`secretaria.maria@htqpjb.gob.do`|`Secretaria123!`|
|Secretaria|`secretaria.juana@htqpjb.gob.do`|`Secretaria123!`|
|Secretaria|`secretaria.elena@htqpjb.gob.do`|`Secretaria123!`|
|Secretaria|`secretaria.rosa@htqpjb.gob.do`|`Secretaria123!`|
|Médico (Ortopedia)|`dr.jperez@htqpjb.gob.do`|`Medico123!`|
|Médico (Medicina Interna)|`dra.aramirez@htqpjb.gob.do`|`Medico123!`|
|Médico (Cirugía General)|`dr.cgarcia@htqpjb.gob.do`|`Medico123!`|
|Médico (Oftalmología)|`dra.lcastillo@htqpjb.gob.do`|`Medico123!`|
|Médico (Neurocirugía)|`dr.rsantos@htqpjb.gob.do`|`Medico123!`|
|Médico inactivo (prueba)|`dr.inactivo@htqpjb.gob.do`|`Medico123!`|

> **Importante:** cambiar inmediatamente todas las contraseñas tras la primera puesta en marcha en producción.

### Datos de demostración (seeders)

El módulo `app.db.seed` puebla la base de datos del HTQPJB con datos realistas para que el sistema sea usable desde el primer arranque. Cada función es **idempotente**: ejecutarla dos veces no duplica datos.

|Entidad|Cantidad|Detalles|
|---|---|---|
|Usuarios|11|1 admin + 4 secretarias + 5 médicos activos + 1 médico inactivo|
|Médicos|9 (8 activos + 1 inactivo)|Cubren 11 de las 18 especialidades oficiales|
|Horarios|L-V mañana/tarde y sábados mañana|7:00–12:00 y 14:00–17:00 entre semana; 8:00–12:00 los sábados|
|Pacientes|40|Cédulas dominicanas con dígito verificador real, edades 5–85, los 4 valores de sexo|
|Citas|50|30% pendientes futuras, 30% atendidas pasadas, 10% canceladas, 30% próximos 3 días|
|Consultas|≥15|Una por cada cita atendida, con los 5 campos clínicos plausibles según especialidad|
|Auditoría|Coherente|Cada inserción del seed deja un registro en `auditoria`|

#### Ejecución manual

```bash
# Seed completo (idempotente, no duplica)
docker exec sgcm_api python -m app.scripts.seed_db

# Resetear datos y volver a sembrar (peligroso, solo dev)
docker exec sgcm_api python -m app.scripts.seed_db --reset

# Sembrar solo una sección
docker exec sgcm_api python -m app.scripts.seed_db --solo pacientes
```

Secciones válidas para `--solo`: `usuarios`, `medicos`, `horarios`, `pacientes`, `citas`, `consultas`.

#### Ejecución automática en cada arranque

El contenedor `sgcm_api` corre `docker-entrypoint.sh` antes de iniciar el servidor. Si la variable de entorno **`SGCM_SEED=true`** está definida (en `.env`), el seed se ejecuta automáticamente en cada `docker compose up`. Por defecto **`SGCM_SEED=false`** para evitar que el seed se ejecute en producción.

```bash
# .env para entornos de desarrollo o demos
SGCM_SEED=true
```

> Idempotencia y producción: ejecutar el seed en una BD ya poblada **no es destructivo** — cada función comprueba antes de insertar. Aun así, lo recomendado en producción es dejar `SGCM_SEED=false` y poblar manualmente solo la primera vez.

---

## Estructura del proyecto

```text
sgcm/
├── app/                          Backend Python
│   ├── api/v1/endpoints/         Endpoints REST
│   │   ├── auth.py
│   │   ├── usuarios.py           CRUD + reset de password por admin
│   │   ├── pacientes.py          CRUD + historial-medico
│   │   ├── medicos.py            CRUD, especialidades, /buscar, /proxima-disponibilidad
│   │   ├── citas.py              CRUD + agenda-extendida + feed FullCalendar
│   │   ├── consultas.py          Registro de consultas (rol médico)
│   │   ├── reportes.py           Citas (PDF) y agenda extendida (PDF/Excel)
│   │   ├── reportes_admin.py     Reportes administrativos (usuarios y médicos)
│   │   ├── respaldos.py          CU-16 — gestión de respaldos
│   │   └── auditoria.py
│   ├── core/                     Configuración y seguridad (JWT, bcrypt)
│   ├── db/                       Sesión SQLAlchemy + seeders (seed.py)
│   ├── models/                   Modelos SQLModel (tablas)
│   ├── scripts/                  CLI: seed_db.py (pobla datos del HTQPJB)
│   ├── services/                 Lógica de negocio
│   │   ├── audit.py              Auditoría transaccional
│   │   ├── citas_service.py      Validaciones de disponibilidad
│   │   └── backup/               CU-16 — Strategy: local / externo / nube
│   │       ├── manager.py        Orquesta pg_dump → SHA-256 → estrategia
│   │       ├── local.py
│   │       ├── externo.py
│   │       └── nube/             Stubs S3, GCS y Azure
│   ├── templates/reportes/       Templates HTML para PDFs
│   └── main.py                   Punto de entrada FastAPI
├── docker-entrypoint.sh          Inicializa esquema y ejecuta seed si SGCM_SEED=true
├── alembic/versions/             6 migraciones (0001-0006); la 0006 crea `respaldos`
├── frontend/
│   ├── static/
│   │   ├── css/sgcm.css          Sistema de diseño (incluye `@media print`)
│   │   ├── js/app.js             Módulo JS común (SGCM) + NAV_ITEMS
│   │   ├── vendor/               Tailwind, FullCalendar, Lucide, xlsx (offline)
│   │   └── fonts/inter/          Fuente Inter local (.woff2)
│   └── templates/                Páginas HTML
│       ├── login.html
│       ├── calendar.html         Calendario y modales de cita
│       ├── pacientes.html
│       ├── medicos.html          Médicos y modal de edición
│       ├── agenda.html           Agenda del rol médico
│       ├── agenda-secretaria.html  Agenda extendida con filtros, PDF/Excel/print
│       ├── usuarios.html         Gestión de usuarios (admin)
│       ├── reportes-usuarios.html  Reportes administrativos (admin)
│       ├── respaldos.html        Panel de respaldos CU-16 (admin)
│       └── auditoria.html        Log de auditoría (admin)
├── nginx/                        Configuración Nginx
├── scripts/init.sql              DDL inicial (volumen Postgres)
├── docs/                         Guías operativas (BACKUPS.md, OFFLINE.md)
├── tests/                        Suite pytest
├── .github/workflows/ci.yml      CI con GitHub Actions
├── docker-compose.yml            Orquestación (incluye volumen sgcm_backups)
├── Dockerfile                    Imagen del backend (incluye postgresql-client)
├── requirements.txt              Dependencias Python (incluye openpyxl)
└── .env.example                  Plantilla de variables
```

---

## Casos de uso

El sistema implementa los **16 casos de uso** definidos en el análisis:

|ID|Caso de uso|Roles|
|---|---|---|
|CU-01|Iniciar sesión|Todos|
|CU-02|Cerrar sesión|Todos|
|CU-03|Registrar paciente|Secretaria, Admin|
|CU-04|Buscar paciente|Secretaria, Admin|
|CU-05|Editar paciente|Secretaria, Admin|
|CU-06|Agendar cita|Secretaria, Admin|
|CU-07|Reprogramar cita|Secretaria, Admin|
|CU-08|Cancelar cita|Secretaria, Admin|
|CU-09|Consultar citas|Todos|
|CU-10|Generar reporte PDF|Secretaria, Admin|
|CU-11|Ver agenda diaria|Médico|
|CU-12|Registrar consulta|Médico|
|CU-13|Gestionar usuarios|Admin|
|CU-14|Registrar médico|Admin|
|CU-15|Consultar auditoría|Admin|
|CU-16|Generar respaldo de la base de datos|Admin|

---

## Roles y permisos

|Rol|Permisos|
|---|---|
|Secretaria|Pacientes (CRUD), citas (CRUD), reportes|
|Médico|Solo agenda propia y registro de consultas (con bloqueo temporal)|
|Administrador|Todo lo anterior, más usuarios, médicos, horarios y auditoría|

El RBAC se aplica en **dos capas**: el backend valida cada petición HTTP independientemente del estado del frontend, garantizando seguridad real. El frontend adapta dinámicamente la UI con `data-role` para mejor experiencia.

---

## Endpoints REST

Todas las rutas viven bajo el prefijo `/api/v1`. La especificación OpenAPI
completa (con esquemas y ejemplos) se expone en `/api/v1/docs` (Swagger UI).
En la columna **Rol** se indica el rol mínimo aceptado:
*Todos* = cualquier usuario autenticado, *Staff* = secretaria o admin.

### Autenticación

| Método | Ruta                         | Rol     | Descripción                                  |
|--------|------------------------------|---------|----------------------------------------------|
| POST   | `/auth/login`                | público | Devuelve un JWT a partir de email/contraseña |
| GET    | `/auth/me`                   | Todos   | Datos del usuario autenticado actual         |

### Usuarios (Admin)

| Método | Ruta                                    | Rol   | Descripción                                                   |
|--------|-----------------------------------------|-------|---------------------------------------------------------------|
| GET    | `/usuarios`                             | Admin | Lista usuarios; filtros `?rol=` y `?sin_perfil_medico=true`   |
| POST   | `/usuarios`                             | Admin | Alta de usuario                                               |
| PATCH  | `/usuarios/{id}`                        | Admin | Actualiza datos del usuario                                   |
| PATCH  | `/usuarios/{id}/password`               | Admin | Reset de contraseña sin requerir la anterior (auditado)       |
| DELETE | `/usuarios/{id}`                        | Admin | Soft delete (preserva FK en citas/auditoría)                  |

### Médicos

| Método | Ruta                                              | Rol   | Descripción                                                                  |
|--------|---------------------------------------------------|-------|------------------------------------------------------------------------------|
| GET    | `/medicos`                                        | Todos | Lista médicos activos                                                        |
| GET    | `/medicos/especialidades`                         | Todos | Catálogo oficial HTQPJB (18 especialidades)                                  |
| GET    | `/medicos/buscar?q=&incluir_inactivos=`           | Todos | Autocomplete por nombre (limit 20)                                           |
| GET    | `/medicos/{id}/proxima-disponibilidad`            | Todos | Sugerencia de slot libre (granularidad 30 min, horizonte 30 días)            |
| POST   | `/medicos`                                        | Admin | Alta de perfil médico (puede vincular usuario existente)                     |
| POST   | `/medicos/con-usuario`                            | Admin | Crea usuario rol=medico + perfil médico en una transacción                   |
| PATCH  | `/medicos/{id}`                                   | Admin | Actualiza perfil médico                                                      |
| GET    | `/medicos/{id}/horarios`                          | Todos | Lista horarios del médico                                                    |
| POST   | `/medicos/{id}/horarios`                          | Admin | Alta de horario                                                              |
| DELETE | `/medicos/horarios/{horario_id}`                  | Admin | Baja de horario                                                              |

### Pacientes

| Método | Ruta                                       | Rol   | Descripción                                                       |
|--------|--------------------------------------------|-------|-------------------------------------------------------------------|
| GET    | `/pacientes`                               | Todos | Lista pacientes                                                   |
| GET    | `/pacientes/{id}`                          | Todos | Detalle                                                           |
| POST   | `/pacientes`                               | Staff | Alta (valida cédula dominicana con dígito verificador)            |
| PATCH  | `/pacientes/{id}`                          | Staff | Actualización                                                     |
| GET    | `/pacientes/{id}/historial-medico?medico_id=` | Todos | Consultas atendidas (DESC), filtro opcional por médico         |
| DELETE | `/pacientes/{id}`                          | Staff | Baja                                                              |

### Citas y consultas

| Método | Ruta                                                                                  | Rol   | Descripción                                                                |
|--------|---------------------------------------------------------------------------------------|-------|----------------------------------------------------------------------------|
| GET    | `/citas?desde=&hasta=&id_medico=&estado=`                                             | Todos | Listado básico                                                             |
| GET    | `/citas/agenda-extendida?id_medico=&fecha_desde=&fecha_hasta=&estado=&especialidad=&busqueda_medico=` | Staff | Agenda enriquecida con conteos por estado |
| GET    | `/citas/calendar?start=&end=&id_medico=`                                              | Todos | Feed en formato FullCalendar                                               |
| POST   | `/citas`                                                                              | Staff | Crea cita (valida E-005 / E-006)                                           |
| PATCH  | `/citas/{id}`                                                                         | Staff | Reprograma (revalida disponibilidad)                                       |
| DELETE | `/citas/{id}`                                                                         | Staff | Cancela (libera el slot del índice parcial)                                |
| GET    | `/consultas/agenda`                                                                   | Médico| Agenda del médico autenticado                                              |
| POST   | `/consultas`                                                                          | Médico| Registra consulta (bloqueo temporal: no antes de la fecha/hora de la cita) |

### Reportes

| Método | Ruta                                                                          | Rol   | Descripción                                                                  |
|--------|-------------------------------------------------------------------------------|-------|------------------------------------------------------------------------------|
| GET    | `/reportes/citas.pdf?desde=&hasta=&id_medico=`                                | Todos | PDF de citas por rango con resumen por estado                                |
| GET    | `/reportes/agenda/pdf?id_medico=&fecha_desde=&fecha_hasta=&estado=&especialidad=&busqueda_medico=` | Staff | PDF (A4 horizontal) de la agenda extendida |
| GET    | `/reportes/agenda/excel?…` *(mismos filtros)*                                 | Staff | Exportación `.xlsx` (openpyxl)                                               |
| GET    | `/reportes/usuarios/resumen`                                                  | Admin | JSON con conteos por rol y estado                                            |
| GET    | `/reportes/usuarios/pdf`                                                      | Admin | PDF con resumen + detalle de usuarios + estadísticas adicionales             |
| GET    | `/reportes/medicos/detalle`                                                   | Admin | JSON con estadísticas por médico activo                                      |
| GET    | `/reportes/medicos/pdf`                                                       | Admin | PDF con listado de médicos activos y resumen final                           |

### Respaldos (Admin · CU-16)

| Método | Ruta                                                              | Rol   | Descripción                                                                  |
|--------|-------------------------------------------------------------------|-------|------------------------------------------------------------------------------|
| POST   | `/respaldos`                                                      | Admin | Crea respaldo (`tipo=local|externo|nube`, `proveedor_nube=s3|gcs|azure`)     |
| GET    | `/respaldos?tipo=&estado=&desde=&hasta=&limit=&offset=`           | Admin | Histórico con filtros                                                        |
| GET    | `/respaldos/{id}`                                                 | Admin | Detalle de un respaldo                                                       |
| DELETE | `/respaldos/{id}`                                                 | Admin | Elimina el registro (no el archivo físico; auditado)                         |
| GET    | `/respaldos/{id}/descargar`                                       | Admin | Descarga el `.sql` (solo respaldos tipo `local`)                             |

### Auditoría y metadatos

| Método | Ruta                          | Rol     | Descripción                                                                  |
|--------|-------------------------------|---------|------------------------------------------------------------------------------|
| GET    | `/auditoria`                  | Admin   | Bitácora paginada de operaciones críticas                                    |
| GET    | `/_debug/rutas`               | público | Lista las rutas registradas (útil para verificar la versión tras un rebuild) |
| GET    | `/health` *(fuera de /api/v1)*| público | Health-check                                                                 |

---

## Variables de entorno

La plantilla completa vive en [`.env.example`](.env.example). A continuación
las variables introducidas en las últimas iteraciones (las demás —`JWT_*`,
`POSTGRES_*`, `BACKEND_CORS_ORIGINS`— están documentadas en el propio
archivo):

| Variable                       | Default                     | Descripción                                                                       |
|--------------------------------|-----------------------------|-----------------------------------------------------------------------------------|
| `SGCM_SEED`                    | `false`                     | Si es `true`, el contenedor `api` ejecuta `app.scripts.seed_db` al arrancar       |
| `SGCM_BACKUP_LOCAL_DIR`        | `/var/backups/sgcm`         | Carpeta del servidor donde se almacenan los respaldos locales                     |
| `SGCM_BACKUP_EXTERNAL_DIR`     | `/mnt/backup_externo`       | Punto de montaje del medio externo (USB / ruta UNC) para respaldos externos       |
| `SGCM_BACKUP_S3_BUCKET`        | *(vacío)*                   | Bucket S3 destino — andamiaje, no funcional aún                                   |
| `SGCM_BACKUP_S3_REGION`        | *(vacío)*                   | Región AWS — andamiaje, no funcional aún                                          |
| `SGCM_BACKUP_GCS_BUCKET`       | *(vacío)*                   | Bucket Google Cloud Storage — andamiaje, no funcional aún                         |
| `SGCM_BACKUP_AZURE_CONTAINER`  | *(vacío)*                   | Contenedor Azure Blob — andamiaje, no funcional aún                               |

> **Nota sobre la nube:** las tres estrategias (`s3`, `gcs`, `azure`) están
> implementadas como *stubs* (`NotImplementedError` con mensaje guía). El
> botón "Nube" de `/respaldos.html` aparece deshabilitado y los endpoints
> devuelven `fallido` con `mensaje_error` orientativo. Para activarlas hay
> que instalar el SDK del proveedor, completar las credenciales y rellenar
> el cuerpo de `app/services/backup/nube/{s3,gcs,azure}.py`. La guía paso a
> paso está en [`docs/BACKUPS.md`](docs/BACKUPS.md).

---

## Migraciones de base de datos

El esquema actual está consolidado en `scripts/init.sql` (se aplica al
crear el volumen `sgcm_pgdata` por primera vez). Para mantener historial
versionado y permitir upgrades futuros sobre BDs existentes, el proyecto
mantiene **6 migraciones Alembic reversibles** en `alembic/versions/`:

| Revisión | Archivo                                          | Cambio principal                                                                   |
|----------|--------------------------------------------------|------------------------------------------------------------------------------------|
| `0001`   | `0001_initial.py`                                | Esquema inicial (preexistente, desincronizado con `init.sql`; no se reaplica)      |
| `0002`   | `0002_pacientes_sexo_fecha_nacimiento.py`        | `pacientes.sexo` NOT NULL (CHECK 4 valores) + `fecha_nacimiento` NOT NULL          |
| `0003`   | `0003_medicos_especialidades_secundarias.py`     | `medicos.especialidad_secundaria_1` y `_2` (nullable)                              |
| `0004`   | `0004_auditoria_nombre_usuario.py`               | Denormaliza `auditoria.nombre_usuario` NOT NULL                                    |
| `0005`   | `0005_consultas_diagnostico_estructurado.py`     | 5 campos clínicos en `consultas` (motivo, examen físico, condiciones, tratamiento) |
| `0006`   | `0006_respaldos.py`                              | Crea la tabla `respaldos` + 2 índices                                              |

Aplicación:

```bash
docker exec sgcm_api alembic upgrade head    # despliegue normal sobre BD existente
docker exec sgcm_api alembic current         # ver revisión activa
docker exec sgcm_api alembic stamp head      # marcar como aplicadas cuando la BD vino de init.sql
```

---

## Pruebas automatizadas

```bash
# Ejecutar todos los tests dentro del contenedor
docker exec sgcm_api pytest -v

# Con cobertura
docker exec sgcm_api pytest --cov=app --cov-report=term-missing
```

Los tests usan **SQLite en memoria** con `StaticPool` para aislamiento y velocidad. Cubren autenticación, RBAC, CRUDs, índice único parcial, validación de cédula dominicana, bloqueo temporal del registro de consulta, vinculación de usuarios con perfiles de médico, generación de reportes y auditoría transaccional.

---

## Integración continua

El workflow `.github/workflows/ci.yml` se ejecuta ante cada push y pull request:

- **Job 1: Tests + Lint.** Instala dependencias, ejecuta `ruff` y la suite completa de `pytest`.
- **Job 2: Docker build.** Construye la imagen Docker validando que el artefacto sea desplegable.

Las versiones de WeasyPrint y pydyf están **fijadas explícitamente** en `requirements.txt` para evitar fallos derivados de cambios incompatibles entre versiones menores.

### Badge de estado

El badge de CI en la cabecera apunta a `https://img.shields.io/github/actions/workflow/status/je7remy/HTQ_Citas/ci.yml`. Si el repositorio es privado, shields.io no puede leer el estado y mostrará "no status". En ese caso usar el badge nativo de GitHub, que funciona si el visitante está autenticado:

```markdown
[![CI](https://github.com/je7remy/HTQ_Citas/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/je7remy/HTQ_Citas/actions/workflows/ci.yml)
```

Como alternativa siempre disponible, la pestaña **Actions** del repositorio refleja el estado actual del último run.

---

## Comandos útiles

|Acción|Comando|
|---|---|
|Arrancar el sistema|`docker compose up -d`|
|Detener el sistema|`docker compose down`|
|Ver logs en vivo|`docker compose logs -f`|
|Reiniciar tras cambios HTML/JS|`docker compose restart nginx`|
|Reiniciar tras cambios Python|`docker compose restart api`|
|Reconstruir tras cambios mayores|`docker compose up -d --build`|
|Ejecutar migraciones|`docker exec sgcm_api alembic upgrade head`|
|Acceder a la base de datos|`docker exec -it sgcm_db psql -U sgcm_user -d sgcm_db`|
|Ejecutar tests|`docker exec sgcm_api pytest -v`|

---

## Documentación

Las guías operativas detalladas viven bajo `docs/` para no inflar este
README:

| Documento | Contenido |
|---|---|
| [`docs/BACKUPS.md`](docs/BACKUPS.md) | Flujo completo de respaldos (CU-16), montaje de disco USB en Linux, roadmap de activación de nube con *snippets* por SDK, restauración con `psql` / `pg_restore`, política de retención sugerida y referencia API. |
| [`docs/OFFLINE.md`](docs/OFFLINE.md) | Cómo se sirven Tailwind, FullCalendar, Lucide, xlsx y la fuente Inter desde `frontend/static/vendor/`, política de cache y procedimiento para actualizar una dependencia. |

La especificación OpenAPI viva del backend está siempre disponible en
`http://<host>/api/v1/docs` (Swagger UI) y `http://<host>/api/v1/openapi.json`.

---

## Respaldos del sistema

> ⚠️ **Si está actualizando desde una versión sin CU-16**, ejecute estos
> tres pasos antes de usar las pantallas (de lo contrario el navegador
> recibirá errores HTTP, ya que el contenedor api todavía no tiene
> `pg_dump` ni la tabla `respaldos`):
>
> ```bash
> docker compose build --no-cache api
> docker compose up -d
> docker exec sgcm_api alembic upgrade head
> ```
>
> Verifique con `curl -s http://localhost/api/v1/_debug/rutas` que los
> endpoints `/respaldos`, `/citas/agenda-extendida` y
> `/reportes/usuarios/resumen` aparecen en la lista.

El SGCM incluye un módulo de respaldos (**CU-16**, panel `/respaldos.html`,
solo administrador) con tres modalidades:

- **Local** — el `.sql` se guarda en `SGCM_BACKUP_LOCAL_DIR` (por defecto
  `/var/backups/sgcm`) del propio servidor. Listo para usarse.
- **Externo** — el `.sql` se copia a `SGCM_BACKUP_EXTERNAL_DIR` (por defecto
  `/mnt/backup_externo`), pensado para disco USB rotativo o ruta UNC. Listo
  para usarse cuando el medio esté montado en el host.
- **Nube** — andamiaje con stubs para Amazon S3, Google Cloud Storage y
  Azure Blob Storage. El botón aparece deshabilitado hasta que se instale
  el SDK del proveedor y se configuren las credenciales.

Cada respaldo:

1. Genera un volcado SQL con `pg_dump` contra el contenedor `db`.
2. Calcula SHA-256 del archivo origen.
3. Lo entrega al destino usando el patrón **Strategy**
   (`app/services/backup/`).
4. Verifica integridad re-calculando el hash en destino.
5. Registra metadatos completos (usuario, tamaño, duración, estado, hash,
   error si lo hubiera) en la tabla `respaldos`.

| Acción                       | Endpoint                                |
|------------------------------|-----------------------------------------|
| Crear respaldo               | `POST /api/v1/respaldos`                |
| Listar histórico             | `GET /api/v1/respaldos`                 |
| Detalle                      | `GET /api/v1/respaldos/{id}`            |
| Eliminar registro            | `DELETE /api/v1/respaldos/{id}`         |
| Descargar `.sql` (solo local)| `GET /api/v1/respaldos/{id}/descargar`  |

Variables relevantes del `.env`:

```env
SGCM_BACKUP_LOCAL_DIR=/var/backups/sgcm
SGCM_BACKUP_EXTERNAL_DIR=/mnt/backup_externo
SGCM_BACKUP_S3_BUCKET=
SGCM_BACKUP_S3_REGION=
SGCM_BACKUP_GCS_BUCKET=
SGCM_BACKUP_AZURE_CONTAINER=
```

La guía operativa completa (montar disco USB, activar respaldo en nube,
restaurar con `psql`/`pg_restore`, política de retención sugerida) está
en [`docs/BACKUPS.md`](docs/BACKUPS.md).

---

## Operación sin internet (offline)

El SGCM está diseñado para correr en la intranet del HTQPJB sin necesidad de
salida a internet en el servidor. Todas las dependencias del frontend
(Tailwind CSS, FullCalendar 6.1.15, Lucide Icons, xlsx 0.18.5 y la fuente
Inter) se sirven localmente desde Nginx:

```
frontend/static/
├── vendor/
│   ├── tailwind/tailwind.min.js          (~440 KB)
│   ├── lucide/lucide.min.js              (~350 KB)
│   ├── fullcalendar/fullcalendar.min.js  (~280 KB)
│   ├── fullcalendar/locales-es.min.js    (~1 KB)
│   └── xlsx/xlsx.full.min.js             (~860 KB)
└── fonts/inter/
    ├── inter.css
    ├── inter-latin.woff2
    └── inter-latin-ext.woff2
```

Procedimiento de verificación, política de cache y cómo actualizar una
dependencia en el futuro: [`docs/OFFLINE.md`](docs/OFFLINE.md).

---

## Cumplimiento legal

El sistema cumple con la **Ley 172-13 sobre Protección de Datos de Carácter Personal** de la República Dominicana mediante:

- Hashing bcrypt de contraseñas (nunca en texto plano).
- Comunicación cifrada HTTPS vía Nginx con certificado SSL.
- Tokens JWT firmados con clave secreta y expiración configurable.
- Auditoría transaccional inmutable de todas las operaciones críticas.
- Control de acceso basado en roles con principio de mínimo privilegio.

---

## Autores

**Cristopher Rafael Marcial** — Matrícula 21-1969

**Jeremy José de la Cruz Pérez** — Matrícula 21-0266

**Asesor:** Lic. David D'Oleo

Universidad Nacional Pedro Henríquez Ureña (UNPHU) — Recinto La Vega

Facultad de Ciencias y Tecnología, Escuela de Informática

La Vega, República Dominicana — 2026

---

## Versión

**SGCM v33.1** — Mayo 2026