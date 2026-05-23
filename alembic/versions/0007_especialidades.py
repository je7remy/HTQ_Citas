"""especialidades: catalogo administrable (CU-17)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-22

Crea la tabla `especialidades` para gestionar el catalogo oficial del HTQPJB
desde el panel admin. Se siembran las 18 especialidades iniciales tomadas del
catalogo legado (`app/core/especialidades.py`). El campo `medicos.especialidad`
se conserva como VARCHAR (sin FK) para no romper la base instalada; la
validacion contra esta tabla se hace a nivel de servicio en el backend.

CONTEXTO (CU-17): antes el catálogo vivía hardcodeado en un módulo Python.
Cada vez que el HTQPJB quería agregar/renombrar una especialidad había que
modificar código y desplegar. Ahora el admin lo hace desde la pantalla
/especialidades.html.

DECISIÓN: no usar FK desde `medicos.especialidad` al catálogo porque:
  - Hay registros legacy de médicos con especialidades que tal vez no
    estén en el catálogo inicial (datos importados).
  - El rename necesita propagar a `medicos.especialidad` (la hace el
    endpoint PATCH en código de aplicación), no romper.
  - Eliminar especialidad se chequea contra `medicos` por código, no
    se delega a una restricción ON DELETE RESTRICT.

OJO: el bulk_insert se duplica con init.sql (ambos insertan las 18
especialidades). En instalación nueva no hay conflicto porque
docker-entrypoint NO ejecuta `alembic upgrade` automáticamente — solo
corre init_db() (SQLModel create_all) e init.sql. El bulk_insert
SOLO importa si alguien corre manualmente `alembic upgrade head`
sobre una BD que pase por 0006 hacia 0007.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Catalogo inicial — copia exacta de las 18 especialidades oficiales del HTQPJB.
# Se mantiene literal aqui porque las migraciones deben ser autocontenidas
# (no deben depender de imports de codigo de aplicacion que pueden cambiar).
_ESPECIALIDADES_INICIALES: tuple[str, ...] = (
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


def upgrade() -> None:
    op.create_table(
        "especialidades",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("nombre", sa.String(length=50), nullable=False),
        sa.Column("descripcion", sa.String(length=200), nullable=True),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "fecha_creacion",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", name="uq_especialidades_nombre"),
    )
    op.create_index(
        "idx_especialidades_activa", "especialidades", ["activa"], unique=False
    )

    # Inserto el catalogo inicial. En despliegues nuevos init.sql ya crea la
    # tabla con estos mismos 18 registros y luego se hace `alembic stamp head`,
    # asi que el INSERT aqui solo corre cuando 0007 se aplica via
    # `alembic upgrade` sobre una BD existente sin la tabla.
    especialidades = sa.table(
        "especialidades",
        sa.column("nombre", sa.String),
        sa.column("activa", sa.Boolean),
    )
    op.bulk_insert(
        especialidades,
        [{"nombre": n, "activa": True} for n in _ESPECIALIDADES_INICIALES],
    )


def downgrade() -> None:
    op.drop_index("idx_especialidades_activa", table_name="especialidades")
    op.drop_table("especialidades")
