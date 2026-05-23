"""Fixtures de pytest: BD SQLite en memoria + cliente FastAPI con override.

Notas:
- Para tests usamos SQLite in-memory en lugar de PostgreSQL para velocidad y aislamiento.
- Los CHECK constraints y UNIQUE de SQLModel/SQLAlchemy también funcionan en SQLite,
  por lo que podemos validar la restricción UNIQUE(id_medico, fecha, hora).

CONTEXTO: este conftest es el corazón del suite de 197 tests. Tres
piezas clave:
  1. `engine` (function-scope): crea SQLite in-memory POR TEST y siembra
     las 18 especialidades. Drop al final del test = aislamiento total.
  2. StaticPool: necesario para que las conexiones SQLite vean la MISMA
     BD in-memory. Sin StaticPool, cada conexión ve una BD vacía y los
     tests se rompen aleatoriamente.
  3. `client` con `dependency_overrides[get_session]`: el TestClient
     comparte la sesión del test en vez de abrir una nueva por request,
     así los datos creados en setup son visibles para el endpoint.

IMPORTANTE: si añades una tabla nueva al modelo, los tests deben seguir
pasando sin tocar conftest — `SQLModel.metadata.create_all` toma TODO
lo declarado en `app/models`. Solo hay que extender este archivo si
necesitas un seed adicional (como el de especialidades).

OJO: la lista ESPECIALIDADES_HTQPJB_SEED DEBE coincidir con la de
init.sql y la de la migración 0007. Si se agrega/quita una en backend,
también acá. NO importamos de un módulo común a propósito — el
conftest debe ser autocontenido y resistente a refactors del backend.
"""
from datetime import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.api.deps import get_current_user
from app.core.security import hash_password
from app.db.session import get_session
from app.main import app
from app.models import Especialidad, Horario, Medico, RolUsuario, Usuario

# Contraseña centralizada para todos los tests. Nunca usar literales reales en los módulos de test.
TEST_PASSWORD = "test-password-fixture-only"

# Catálogo inicial sembrado tras crear el esquema en cada test.
# Es el mismo bloque que aplican `scripts/init.sql` y la migración 0007 en
# entornos reales — aquí lo replicamos porque SQLite usa create_all() puro,
# sin ejecutar SQL fuera del esquema de SQLModel.
ESPECIALIDADES_HTQPJB_SEED: tuple[str, ...] = (
    "Ortopedia y Traumatología",
    "Cirugía General",
    "Cirugía Vascular",
    "Cirugía Torácica",
    "Cirugía Plástica",
    "Cirugía Pediátrica",
    "Cirugía Ginecológica",
    "Neurocirugía",
    "Cirugía Maxilofacial",
    "Anestesiología",
    "Medicina Interna",
    "Urología",
    "Oftalmología",
    "Otorrinolaringología",
    "Medicina Física y Rehabilitación",
    "Radiología y Diagnóstico por Imágenes",
    "Laboratorio Clínico",
    "Emergenciología",
)


@pytest.fixture
def test_password() -> str:
    return TEST_PASSWORD


@pytest.fixture(name="engine")
def engine_fixture():
    # "sqlite://" sin path = BD in-memory. Vive solo mientras existe
    # el engine, y desaparece al final del fixture.
    # check_same_thread=False: SQLite por defecto solo permite una
    # conexión por thread; el TestClient de FastAPI puede usar threads
    # distintos para servir requests. Sin este flag, tests con threads
    # truenan con "SQLite objects created in a thread...".
    # StaticPool: ver el docstring del módulo.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        for nombre in ESPECIALIDADES_HTQPJB_SEED:
            s.add(Especialidad(nombre=nombre, activa=True))
        s.commit()
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture(name="seed_users")
def seed_users_fixture(session: Session):
    """Crea admin, secretaria y un médico con horario L-V 8-12."""
    admin = Usuario(
        nombre="Admin Test",
        email="admin@test.do",
        password_hash=hash_password(TEST_PASSWORD),
        rol=RolUsuario.admin,
    )
    sec = Usuario(
        nombre="Secre Test",
        email="sec@test.do",
        password_hash=hash_password(TEST_PASSWORD),
        rol=RolUsuario.secretaria,
    )
    med_user = Usuario(
        nombre="Dr. Test",
        email="med@test.do",
        password_hash=hash_password(TEST_PASSWORD),
        rol=RolUsuario.medico,
    )
    session.add_all([admin, sec, med_user])
    session.flush()

    medico = Medico(
        id_usuario=med_user.id,
        nombre="Dr. Test",
        especialidad="Ortopedia y Traumatología",
    )
    session.add(medico)
    session.flush()

    for dia in range(1, 6):  # L-V
        session.add(
            Horario(
                id_medico=medico.id,
                dia_semana=dia,
                hora_inicio=time(8, 0),
                hora_fin=time(12, 0),
            )
        )
    session.commit()
    return {"admin": admin, "secretaria": sec, "medico_user": med_user, "medico": medico}


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def _get_session_override():
        yield session

    app.dependency_overrides[get_session] = _get_session_override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(name="auth_as")
def auth_as_fixture(client: TestClient, session: Session, seed_users):
    """Devuelve una función que autentica al cliente como un rol dado.

    Hacemos override de get_current_user en lugar de hacer login real,
    porque login emite tokens con expiración real y queremos tests rápidos.

    Uso típico en un test:
        def test_x(auth_as, client):
            actor = auth_as("admin")  # ahora client va como admin
            ...

    OJO: el override es GLOBAL al `app.dependency_overrides`. Si un
    test llama auth_as("admin") y luego auth_as("medico"), el segundo
    pisa al primero — es el comportamiento deseado para cambiar de
    rol mid-test. El `client` fixture limpia los overrides al final.
    """
    def _login(rol: str) -> Usuario:
        mapping = {
            "admin": seed_users["admin"],
            "secretaria": seed_users["secretaria"],
            "medico": seed_users["medico_user"],
        }
        user = mapping[rol]

        def _override():
            return user

        app.dependency_overrides[get_current_user] = _override
        return user

    return _login
