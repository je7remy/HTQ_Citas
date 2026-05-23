"""respaldos: bitácora de respaldos (local, externo, nube)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-16

Crea la tabla `respaldos` que registra cada copia de seguridad
generada por un administrador desde el panel /respaldos.html.

CONTEXTO (CU-16): el admin debe poder generar respaldos manualmente y
ver el histórico. Cada intento queda en BD aunque falle, con
mensaje_error explicativo (de qué falló pg_dump, qué USB no estaba
montado, etc.).

DOS INDICES creados a propósito:
  - idx_respaldos_fecha_inicio: la pantalla de respaldos ordena
    DESC por fecha — sin este índice el ORDER BY se vuelve seq scan
    con miles de filas.
  - idx_respaldos_tipo_estado: el filtro "ver solo fallidos de tipo
    nube" lo usa para ir directo sin escanear todo.

VARCHAR + CHECK para tipo/proveedor/estado (no Enum nativo de Postgres)
por la misma razón que el modelo Respaldo: portabilidad y libertad de
agregar/quitar valores sin DDL pesado. Ver decisión en
app/models/__init__.py.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "respaldos",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("id_usuario", sa.Integer(), nullable=True),
        sa.Column("nombre_usuario", sa.String(length=100), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("proveedor_nube", sa.String(length=20), nullable=True),
        sa.Column("ruta_origen", sa.Text(), nullable=False),
        sa.Column("ruta_destino", sa.Text(), nullable=False),
        sa.Column("tamano_bytes", sa.BigInteger(), nullable=False),
        sa.Column("hash_sha256", sa.String(length=64), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("mensaje_error", sa.Text(), nullable=True),
        sa.Column(
            "fecha_inicio",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("fecha_fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duracion_segundos", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["id_usuario"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "tipo IN ('local','externo','nube')",
            name="ck_respaldos_tipo",
        ),
        sa.CheckConstraint(
            "proveedor_nube IS NULL OR proveedor_nube IN ('s3','gcs','azure')",
            name="ck_respaldos_proveedor_nube",
        ),
        sa.CheckConstraint(
            "estado IN ('en_progreso','completado','fallido')",
            name="ck_respaldos_estado",
        ),
    )
    op.create_index(
        "idx_respaldos_fecha_inicio", "respaldos", ["fecha_inicio"], unique=False
    )
    op.create_index(
        "idx_respaldos_tipo_estado", "respaldos", ["tipo", "estado"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_respaldos_tipo_estado", table_name="respaldos")
    op.drop_index("idx_respaldos_fecha_inicio", table_name="respaldos")
    op.drop_table("respaldos")
