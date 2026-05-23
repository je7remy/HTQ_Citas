"""Configuración de entorno de Alembic para SGCM.

CONTEXTO: en este proyecto Alembic NO se ejecuta automáticamente. El
docker-entrypoint.sh usa `init_db()` (que llama a
`SQLModel.metadata.create_all`) para crear las tablas, y por separado
PostgreSQL corre `init.sql` al crear el volumen por primera vez.

Las migraciones bajo `versions/` quedan como DOCUMENTACIÓN HISTÓRICA
de los cambios incrementales (0002-0007). Para correr alguna se
invoca manualmente: `docker compose exec api alembic upgrade head`.

CUIDADO: el archivo 0001_initial.py NO refleja el esquema actual — es
una captura histórica del primer esquema (antes de los renombrados que
hoy viven en init.sql). Si corres `alembic upgrade head` desde una BD
vacía, terminas con un esquema DISTINTO al de producción (ver
"Observaciones de código" del Lote 3 para los detalles).

`target_metadata = SQLModel.metadata` permite a Alembic detectar drift
con `alembic revision --autogenerate` — usa los modelos SQLModel como
fuente de verdad.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from app.core.config import settings
from app import models  # noqa: F401  -- registrar metadatos

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
