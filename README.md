# SGCM — Sistema Web de Gestión de Citas Médicas

  

[![![CI](https://github.com/je7remy/HTQ_Citas/actions/workflows/ci.yml/badge.svg)](https://github.com/je7remy/HTQ_Citas/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791.svg)
![Docker](https://img.shields.io/badge/Docker-24+-2496ED.svg)
![License](https://img.shields.io/badge/license-Académico-lightgrey.svg)

  

Plataforma web para automatizar y optimizar el proceso de gestión de citas médicas del **Hospital Regional Traumatológico y Quirúrgico Prof. Juan Bosch (HTQPJB)** en La Vega, República Dominicana.

  

> Trabajo de grado para optar por el título de Licenciatura en Informática — Universidad Nacional Pedro Henríquez Ureña (UNPHU), Recinto La Vega.

  

---

  

## Tabla de contenido

  

- [Sobre el proyecto](#sobre-el-proyecto)

- [Características principales](#características-principales)

- [Arquitectura](#arquitectura)

- [Stack tecnológico](#stack-tecnológico)

- [Inicio rápido](#inicio-rápido)

- [Estructura del proyecto](#estructura-del-proyecto)

- [Casos de uso](#casos-de-uso)

- [Roles y permisos](#roles-y-permisos)

- [Pruebas automatizadas](#pruebas-automatizadas)

- [Integración continua](#integración-continua)

- [Documentación](#documentación)

- [Autores](#autores)

  

---

  

## Sobre el proyecto

  

El SGCM automatiza el proceso de gestión de citas que el HTQPJB realizaba previamente con registros físicos, libretas y comunicación verbal. La plataforma reemplaza esos soportes manuales por una solución digital centralizada que opera en la intranet del hospital.

  

**Lo que el sistema NO es:** una reingeniería del proceso institucional. La lógica operativa, los roles y las responsabilidades del personal se conservan. **Lo que el sistema SÍ es:** la automatización de los puntos del flujo donde los soportes manuales generaban duplicaciones, demoras y descoordinación.

  

---

  

## Características principales

  

- 🔐 **Autenticación JWT** con hashing bcrypt y expiración configurable.

- 👥 **Control de acceso basado en roles (RBAC)** en dos capas: backend y frontend.

- 📅 **Calendario interactivo** con FullCalendar.js (vista mensual por defecto).

- 🚫 **Prevención física de duplicaciones** mediante índice único parcial en PostgreSQL.

- 🩺 **Bloqueo temporal del registro de consulta:** el médico no puede registrar diagnósticos antes de la fecha de la cita.

- 🔗 **Vinculación usuario↔médico** desde la UI del administrador.

- 📄 **Reportes PDF** generados con WeasyPrint, con fecha de emisión y numeración secuencial.

- 🔍 **Auditoría transaccional** de todas las operaciones críticas (Ley 172-13).

- ✅ **Suite de ~50 pruebas automatizadas** con pytest.

- 🔄 **CI/CD** con GitHub Actions ejecutando linter, tests y construcción de imagen Docker.

- 🐳 **Despliegue 100% contenedorizado** con Docker Compose.

- 🎨 **Máscaras visuales** en cédula y teléfono para mejor experiencia de usuario.

  

---

  

## Arquitectura

  

```

┌─────────────────────────────────────────────────────────────┐

│                    INTRANET DEL HOSPITAL                    │

│                                                             │

│   Navegador  ──HTTP──▶  ┌──────────┐                        │

│                         │  NGINX   │  (proxy + estáticos)   │

│                         │  :80     │                        │

│                         └─────┬────┘                        │

│                               │                             │

│                       ┌───────┴────────┐                    │

│                       ▼                ▼                    │

│              ┌──────────────┐  ┌──────────────┐             │

│              │   FastAPI    │  │  PostgreSQL  │             │

│              │   :8000      │──│   :5432      │             │

│              │  (backend)   │  │  (database)  │             │

│              └──────────────┘  └──────────────┘             │

│                                                             │

│              Volumen pgdata (persistencia)                  │

└─────────────────────────────────────────────────────────────┘

```

  

---

  

## Stack tecnológico

  

### Backend

- **Python 3.11+** — Lenguaje principal

- **FastAPI** — Framework web asíncrono con OpenAPI automático

- **SQLModel** — ORM combinado con validación Pydantic

- **Alembic** — Migraciones versionadas del esquema

- **python-jose** — Generación y validación de JWT

- **passlib + bcrypt** — Hashing seguro de contraseñas

- **WeasyPrint** — Generación de PDFs desde HTML/CSS

- **pytest + httpx** — Pruebas automatizadas

  

### Base de datos

- **PostgreSQL 15** — Con índices únicos parciales para prevenir duplicaciones

  

### Frontend

- **HTML5 + JavaScript ES6** (vanilla, sin framework)

- **Tailwind CSS** (vía CDN)

- **FullCalendar.js** — Calendario interactivo

  

### Infraestructura

- **Docker + Docker Compose** — Orquestación de contenedores

- **Nginx** — Proxy inverso y servidor de archivos estáticos

- **mkcert** — Certificado SSL para HTTPS en intranet

- **GitHub Actions** — Integración continua

  

---

  

## Inicio rápido

  

### Requisitos previos

- Docker Engine 24+ y Docker Compose v2

- Git 2.30+

  

### Instalación en 4 pasos

  

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

  

| Rol | Email | Contraseña |

|---|---|---|

| Administrador | `admin@htqpjb.gob.do` | `Admin*2026` |

| Secretaria | `secretaria@htqpjb.gob.do` | `Secret*2026` |

| Médico | `jperez@htqpjb.gob.do` | `Medico*2026` |

  

> ⚠️ Cambiar inmediatamente todas las contraseñas tras la primera puesta en marcha en producción.

  

---

  

## Estructura del proyecto

  

```

sgcm/

├── app/                          # Backend Python

│   ├── api/v1/                   # Endpoints REST

│   ├── core/                     # Configuración y seguridad (JWT, bcrypt)

│   ├── db/                       # Sesión SQLAlchemy

│   ├── models/                   # Modelos SQLModel (tablas)

│   ├── services/                 # Lógica de negocio

│   ├── templates/reportes/       # Templates HTML para PDFs

│   └── main.py                   # Punto de entrada FastAPI

├── alembic/                      # Migraciones de base de datos

├── frontend/

│   ├── static/

│   │   └── js/app.js             # Módulo JS común (SGCM)

│   └── templates/                # Páginas HTML

│       ├── login.html

│       ├── calendar.html         # Calendario + modales de cita

│       ├── pacientes.html

│       ├── medicos.html          # Médicos + modal edición

│       ├── agenda.html           # Agenda del rol médico

│       ├── usuarios.html         # Gestión de usuarios (admin)

│       └── auditoria.html        # Log de auditoría (admin)

├── nginx/                        # Configuración Nginx

├── scripts/seed.py               # Datos iniciales

├── tests/                        # Suite pytest

├── .github/workflows/ci.yml      # CI con GitHub Actions

├── docker-compose.yml            # Orquestación

├── Dockerfile                    # Imagen del backend

├── requirements.txt              # Dependencias Python

└── .env.example                  # Plantilla de variables

```

  

---

  

## Casos de uso

  

El sistema implementa los **15 casos de uso** definidos en el análisis:

  

| ID | Caso de uso | Roles |

|---|---|---|

| CU-01 | Iniciar sesión | Todos |

| CU-02 | Cerrar sesión | Todos |

| CU-03 | Registrar paciente | Secretaria, Admin |

| CU-04 | Buscar paciente | Secretaria, Admin |

| CU-05 | Editar paciente | Secretaria, Admin |

| CU-06 | Agendar cita | Secretaria, Admin |

| CU-07 | Reprogramar cita | Secretaria, Admin |

| CU-08 | Cancelar cita | Secretaria, Admin |

| CU-09 | Consultar citas | Todos |

| CU-10 | Generar reporte PDF | Secretaria, Admin |

| CU-11 | Ver agenda diaria | Médico |

| CU-12 | Registrar consulta | Médico |

| CU-13 | Gestionar usuarios | Admin |

| CU-14 | Registrar médico | Admin |

| CU-15 | Consultar auditoría | Admin |

  

---

  

## Roles y permisos

  

| Rol | Permisos |

|---|---|

| **Secretaria** | Pacientes (CRUD), Citas (CRUD), Reportes |

| **Médico** | Solo agenda propia, registro de consultas (con bloqueo temporal) |

| **Administrador** | Todo lo anterior + usuarios, médicos, horarios, auditoría |

  

El RBAC se aplica en **dos capas**: el backend valida cada petición HTTP independientemente del estado del frontend, garantizando seguridad real. El frontend adapta dinámicamente la UI con `data-role` para mejor experiencia.

  

---

  

## Pruebas automatizadas

  

```bash

# Ejecutar todos los tests dentro del contenedor

docker exec sgcm_api pytest -v

  

# Con cobertura

docker exec sgcm_api pytest --cov=app --cov-report=term-missing

```

  

Los tests usan **SQLite en memoria** con `StaticPool` para aislamiento y velocidad. Cubren autenticación, RBAC, CRUDs, índice único parcial, validación de cédula dominicana, bloqueo temporal del registro de consulta, vinculación usuario↔médico, generación de reportes y auditoría transaccional.

  

---

  

## Integración continua

  

El workflow `.github/workflows/ci.yml` se ejecuta ante cada push y pull request:

  

- **Job 1: Tests + Lint** — Instala dependencias, ejecuta `ruff` y la suite completa de `pytest`.

- **Job 2: Docker build** — Construye la imagen Docker validando que el artefacto sea desplegable.

  

Las versiones de WeasyPrint y pydyf están **fijadas explícitamente** en `requirements.txt` para evitar fallos derivados de cambios incompatibles entre versiones menores.

  

---

  

## Comandos útiles

  

| Acción | Comando |

|---|---|

| Arrancar el sistema | `docker compose up -d` |

| Detener el sistema | `docker compose down` |

| Ver logs en vivo | `docker compose logs -f` |

| Reiniciar tras cambios HTML/JS | `docker compose restart nginx` |

| Reiniciar tras cambios Python | `docker compose restart api` |

| Reconstruir tras cambios mayores | `docker compose up -d --build` |

| Ejecutar migraciones | `docker exec sgcm_api alembic upgrade head` |

| Acceder a la base de datos | `docker exec -it sgcm_db psql -U sgcm_user -d sgcm_db` |

| Ejecutar tests | `docker exec sgcm_api pytest -v` |

  

---

  

## Documentación

  

El proyecto incluye documentación complementaria:

  

- **Manual de Usuario** — Para el personal del hospital.

- **Manual de Instalación** — Para el personal técnico.

- **Guía de Configuración Personal** — Procedimiento detallado de despliegue local.

- **Guía de Entendimiento del Proyecto** — Recorrido archivo por archivo del código.

- **Guía de Estudio Profundo** — Testing, CI/CD, auditoría y Docker avanzado.

- **Guía de Demostración para la Defensa** — Guion paso a paso de la presentación.

- **Changelog v1.1** — Registro de cambios desde la entrega inicial.

  

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

Facultad de Ciencias y Tecnología · Escuela de Informática  

La Vega, República Dominicana — 2026

  

---

  

## Versión

  

**SGCM v1.1** — Mayo 2026

  

Ver [Changelog](docs/7-_Changelog_SGCM_v1.1.docx) para el detalle de cambios.

```