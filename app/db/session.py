"""Motor y sesión de SQLModel.

CONTEXTO: este módulo define el engine único que comparten todos los
endpoints. FastAPI inyecta get_session() en cada request vía Depends.
La sesión es per-request: se abre al entrar al endpoint, se commitea
o rollback al final, y se cierra automáticamente.
"""
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

# Configuración del pool:
# - pool_pre_ping=True: hace SELECT 1 antes de entregar cada conexión.
#   Cuesta un round-trip pero detecta conexiones que el servidor cerró
#   por timeout/restart sin que el cliente se entere. Sin esto, el primer
#   request tras un restart del contenedor de Postgres truena.
# - pool_size=10 + max_overflow=20: hasta 30 conexiones concurrentes.
#   Es generoso para el HTQPJB (10-15 usuarios simultáneos pico) y
#   deja margen para spikes de reportes pesados que tardan más.
# - echo=False: no spamea el log con cada SELECT. Para debug local
#   se puede poner True temporalmente.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)


def get_session() -> Generator[Session, None, None]:
    """Generador de sesión para FastAPI Depends.

    Cada request abre una sesión propia; el `with` la cierra al terminar
    aunque el endpoint lance excepción.
    """
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Crear tablas si no existen.

    Esta función la invoca docker-entrypoint.sh al arrancar el
    contenedor api. Funciona en combinación con scripts/init.sql:
      - En instalación nueva, init.sql ya creó las tablas — create_all
        ve que existen y no hace nada.
      - En entornos de test con SQLite in-memory (sin init.sql),
        create_all monta el esquema completo.

    CUIDADO: create_all() NO migra esquemas existentes — si una tabla
    ya existe con columnas distintas, las deja como están y termina
    sin error. Para cambios reales de esquema sobre BD productiva, se
    aplican migraciones Alembic manualmente.
    """
    SQLModel.metadata.create_all(engine)
