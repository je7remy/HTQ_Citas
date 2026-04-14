# SGCM — Sistema Web de Gestión de Citas Médicas

Sistema web para automatizar la gestión de citas médicas del **Hospital Regional Traumatológico y Quirúrgico Prof. Juan Bosch (HTQPJB)**, La Vega, República Dominicana.

Trabajo de grado — Universidad Nacional Pedro Henríquez Ureña (UNPHU), Recinto La Vega.

## Stack tecnológico

| Capa | Tecnologías |
|---|---|
| **Backend** | Python 3.11 · FastAPI · SQLModel · Alembic |
| **Base de datos** | PostgreSQL 15 |
| **Auth** | JWT (python-jose) · bcrypt · RBAC |
| **Frontend** | HTML · Vanilla JS · Tailwind CSS · FullCalendar.js |
| **Reportes** | WeasyPrint (PDF) |
| **Infraestructura** | Docker · Docker Compose · Nginx (reverse proxy) |
| **Tests** | pytest (40+ casos, BD SQLite in-memory) |
| **CI** | GitHub Actions |

## Estructura del proyecto

```
sgcm/
├── app/
│   ├── api/
│   │   ├── deps.py                  # get_current_user + RBAC
│   │   └── v1/
│   │       ├── router.py            # Agregador
│   │       └── endpoints/
│   │           ├── auth.py          # Login (CU-01) + /me
│   │           ├── usuarios.py      # CRUD usuarios (admin)
│   │           ├── pacientes.py     # CRUD pacientes (E-007)
│   │           ├── medicos.py       # CRUD médicos + horarios
│   │           ├── citas.py         # CRUD + feed FullCalendar
│   │           ├── consultas.py     # Módulo médico
│   │           ├── reportes.py      # PDF con WeasyPrint
│   │           └── auditoria.py     # CU-15 consulta auditoría
│   ├── core/                        # Config + JWT/bcrypt
│   ├── db/session.py                # Engine SQLModel
│   ├── models/                      # Tablas (Anexo D)
│   ├── schemas/                     # DTOs Pydantic
│   ├── services/                    # Lógica de negocio + auditoría
│   └── main.py                      # FastAPI factory
├── alembic/                         # Migraciones
├── frontend/
│   ├── templates/
│   │   ├── login.html
│   │   ├── calendar.html            # FullCalendar.js
│   │   ├── pacientes.html           # CRUD pacientes
│   │   ├── medicos.html             # CRUD médicos + horarios
│   │   └── auditoria.html           # CU-15 viewer (admin)
│   └── static/js/app.js             # Cliente JWT
├── nginx/default.conf               # Reverse proxy
├── scripts/
│   ├── init.sql                     # DDL Anexo D + índice parcial
│   └── seed.py                      # Usuarios iniciales
├── tests/                           # 40+ tests pytest
├── .github/workflows/ci.yml         # CI
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── pytest.ini
```

## Arranque rápido

```bash
git clone <repo>
cd sgcm
cp .env.example .env       # Cambia JWT_SECRET_KEY (mín. 32 chars)
docker compose up --build
```

Servicios:

- **Frontend:**     http://localhost/
- **API docs:**     http://localhost/api/v1/docs
- **Health check:** http://localhost/health
- **PostgreSQL:**   localhost:5432

El contenedor `api` ejecuta `scripts/seed.py` automáticamente y crea:

| Rol | Email | Password |
|---|---|---|
| Admin | `admin@htqpjb.gob.do` | `Admin*2026` |
| Secretaria | `secretaria@htqpjb.gob.do` | `Secret*2026` |
| Médico | `jperez@htqpjb.gob.do` | `Medico*2026` |

Más un médico de prueba (Dr. Juan Pérez, Traumatología) con horario L–V 8:00–12:00.

## Casos de uso implementados

| ID | Descripción | Endpoint |
|---|---|---|
| CU-01 | Login con JWT + auditoría | `POST /api/v1/auth/login` |
| CU-02 | Gestión de usuarios (admin) | `*/api/v1/usuarios` |
| CU-03 | Registro de pacientes | `POST /api/v1/pacientes` |
| CU-04 | Búsqueda de pacientes | `GET /api/v1/pacientes?q=...` |
| CU-05 | Crear cita (valida disponibilidad) | `POST /api/v1/citas` |
| CU-06 | Visualización en calendario | `GET /api/v1/citas/calendar` |
| CU-07 | Reprogramar cita (libera horario) | `PATCH /api/v1/citas/{id}` |
| CU-08 | Cancelar cita (libera horario) | `DELETE /api/v1/citas/{id}` |
| CU-09 | Consultar citas con filtros | `GET /api/v1/citas` |
| CU-10 | Gestión de médicos | `*/api/v1/medicos` |
| CU-11 | Gestión de horarios | `*/api/v1/medicos/{id}/horarios` |
| CU-12 | Agenda diaria del médico | `GET /api/v1/consultas/agenda` |
| CU-13 | Registrar observaciones | `POST /api/v1/consultas` |
| CU-14 | Reportes PDF | `GET /api/v1/reportes/citas.pdf` |
| CU-15 | Consulta de auditoría (admin) | `GET /api/v1/auditoria` |

## Códigos de error de negocio

Coinciden con los de la tesis:

| Código | Significado | Causa |
|---|---|---|
| **E-005** | Horario ocupado | Slot ya asignado a una cita activa |
| **E-006** | Fuera de horario | Hora fuera del `Horario` del médico para ese día |
| **E-007** | Cédula duplicada | Violación de `UNIQUE` en `pacientes.cedula` |

## Decisión de diseño: índice único parcial

La tesis exige dos cosas a la vez:

1. **Anexo D:** restricción `UNIQUE(id_medico, fecha, hora)` en `citas`.
2. **CU-07/CU-08/P2.4:** al cancelar o reprogramar, el horario debe quedar **libre**.

Estas dos cosas son incompatibles con un `UNIQUE` total convencional, porque las filas canceladas seguirían bloqueando el slot. La solución es un **índice único parcial** de PostgreSQL:

```sql
CREATE UNIQUE INDEX uq_citas_medico_fecha_hora
    ON citas (id_medico, fecha, hora)
    WHERE estado <> 'cancelada';
```

Esto preserva la integridad anti-duplicados para citas **activas**, permite reutilizar el slot tras cancelación, y conserva las filas canceladas para auditoría y trazabilidad.

## Tests

```bash
# Localmente
pip install -r requirements.txt
JWT_SECRET_KEY=test-secret-key-with-at-least-32-characters \
POSTGRES_USER=x POSTGRES_PASSWORD=x POSTGRES_DB=x \
pytest -v

# En Docker
docker compose exec api pytest -v
```

Cobertura por archivo:

| Archivo | Casos | Cubre |
|---|---|---|
| `test_auth.py` | 6 | Login, RBAC, endpoints protegidos |
| `test_pacientes.py` | 7 | CRUD, E-007, validación de cédula |
| `test_citas.py` | 7 | E-005, E-006, CU-07, CU-08, feed calendar |
| `test_auditoria.py` | 15 | Logs CRUD/LOGIN, atomicidad, CU-15 |
| `test_reportes.py` | 4 | PDF válido, filtros, RBAC |

Los tests usan SQLite in-memory con `StaticPool` para velocidad y aislamiento. Las fechas se calculan dinámicamente para que no caduquen con el tiempo.

## Migraciones (Alembic)

```bash
docker compose exec api alembic revision --autogenerate -m "mensaje"
docker compose exec api alembic upgrade head
```

Para arranque limpio en desarrollo, `scripts/init.sql` se aplica automáticamente vía `docker-entrypoint-initdb.d` de PostgreSQL.

## Seguridad

- **JWT** con expiración configurable (default 60 min) y `JWT_SECRET_KEY` validada con `min_length=32` en el código.
- **bcrypt** para hash de contraseñas vía `passlib`.
- **RBAC** con factory `require_roles(...)` por endpoint.
- **Auditoría transaccional**: cada acción crítica se registra en la misma transacción que la operación principal — si la operación falla, no queda log huérfano.
- **Validación Pydantic** rechaza payloads malformados antes de tocar la BD.
- **Headers de seguridad** en Nginx (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`).
- **Cumplimiento de Ley 172-13** sobre protección de datos personales.

## CI/CD

GitHub Actions corre en cada push/PR:

1. Levanta un servicio PostgreSQL 15.
2. Instala dependencias de WeasyPrint.
3. Ejecuta `ruff check`.
4. Ejecuta `pytest`.
5. Verifica que la imagen Docker compila.

## Licencia

Trabajo de grado académico — UNPHU 2026.
Autores: Cristopher Rafael Marcial · Jeremy José de la Cruz Pérez.
Asesor: Lic. David D'Oleo.
