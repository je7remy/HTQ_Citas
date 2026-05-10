"""auditoria: agregar nombre_usuario denormalizado

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Agregar columna nullable inicialmente, para poder rellenar registros existentes.
    op.add_column(
        "auditoria",
        sa.Column("nombre_usuario", sa.String(length=100), nullable=True),
    )

    # 2. Poblar registros existentes con el nombre actual del usuario referenciado.
    op.execute(
        """
        UPDATE auditoria a
           SET nombre_usuario = COALESCE(u.nombre, '[usuario eliminado]')
          FROM (SELECT id, nombre FROM usuarios) u
         WHERE u.id = a.id_usuario
        """
    )
    # Para los registros con id_usuario NULL o usuario huérfano, asignar placeholder.
    op.execute(
        "UPDATE auditoria SET nombre_usuario = '[usuario eliminado]' "
        "WHERE nombre_usuario IS NULL"
    )

    # 3. Marcar la columna como NOT NULL.
    op.alter_column(
        "auditoria",
        "nombre_usuario",
        existing_type=sa.String(length=100),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("auditoria", "nombre_usuario")
